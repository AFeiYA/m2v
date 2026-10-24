"""Bounded Paddle Billing REST client for the existing Python backend."""
import re
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from src.paddle_config import api_key, environment

BASES = {'sandbox': 'https://sandbox-api.paddle.com', 'production': 'https://api.paddle.com'}


async def request(settings, method, path, payload=None):
    mode = environment(settings)
    if not api_key(settings).startswith('pdl_sdbx_' if mode == 'sandbox' else 'pdl_live_'):
        raise HTTPException(503, 'Paddle API key does not match environment')
    if mode == 'production' and (not settings.PADDLE_LIVE_ENABLED or settings.BILLING_ALLOW_TEST_TRANSACTIONS):
        raise HTTPException(503, 'Live Paddle is not activated')
    if not re.fullmatch(r'(?:transactions(?:/txn_[a-z0-9]{26}(?:/invoice)?)?|subscriptions/sub_[a-z0-9]{26}|adjustments/adj_[a-z0-9]{26}|prices/pri_[a-z0-9]{26}|customers/ctm_[a-z0-9]{26}/portal-sessions|settings/checkout-url|checkout-domains|notification-settings(?:/ntfset_[a-z0-9]{26})?)', path):
        raise ValueError('Invalid Paddle resource')
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.request(method, BASES[mode] + '/' + path,
                headers={'Authorization': 'Bearer ' + api_key(settings), 'Paddle-Version': '1'},
                **({'params': payload} if method.upper() == 'GET' else {'json': payload}))
        if response.status_code >= 300:
            raise HTTPException(502, 'Paddle is temporarily unavailable. Please retry later.')
        data = response.json()
        if not isinstance(data, dict) or 'data' not in data:
            raise ValueError()
        return data
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, 'Paddle is temporarily unavailable. Please retry later.') from None


async def get(settings, path, params=None):
    return (await request(settings, 'GET', path, params))['data']


def safe_url(value, settings, *, invoice=False):
    try:
        p = urlsplit(value) if isinstance(value, str) and len(value) <= 4096 else None
        sandbox = environment(settings) == 'sandbox'
        hosts = {'sandbox-customer-portal.paddle.com'} if sandbox else {'customer-portal.paddle.com'}
        # Invoice API returns a short-lived signed link on Paddle's document host.
        if invoice:
            hosts |= {'sandbox-invoices.paddle.com', 'sandbox-buy.paddle.com'} if sandbox else {'invoices.paddle.com', 'buy.paddle.com'}
        if not p or p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise HTTPException(502, 'Invalid Paddle redirect') from None
    return value


async def validate_product(settings, product):
    price = await get(settings, 'prices/' + product.variant_id)
    cycle = price.get('billing_cycle')
    quantity = price.get('quantity') or {}
    if (price.get('id') != product.variant_id or price.get('status') != 'active'
            or price.get('unit_price') != {'amount': str(product.price_cents), 'currency_code': product.currency}
            or price.get('tax_mode') != 'external' or price.get('trial_period') or price.get('unit_price_overrides')
            or quantity.get('minimum') != 1 or quantity.get('maximum') != 1
            or (product.kind == 'topup' and cycle is not None)
            or (product.kind == 'subscription' and cycle != {'interval': 'month', 'frequency': 1})):
        raise HTTPException(503, 'Paddle price does not match the server catalogue')
    return price


async def preflight(settings, products, *, release=False):
    prices = [await validate_product(settings, p) for p in products.values()]
    if len({p.get('product_id') for p in prices}) != len(prices):
        raise HTTPException(503, 'Use a separate Paddle Product for each package')
    checkout = await get(settings, 'settings/checkout-url')
    if not checkout.get('default_url'):
        raise HTTPException(503, 'Set the Paddle default payment link first')
    url = urlsplit(checkout['default_url'])
    expected = urlsplit(settings.BILLING_SITE_URL)
    if (url.scheme, url.netloc, url.path, url.query, url.fragment) != (expected.scheme, expected.netloc, '/app', '', ''):
        raise HTTPException(503, 'Paddle default payment link must match BILLING_SITE_URL/app')
    if not release:
        return
    if environment(settings) == 'production':
        if not settings.DATABASE_URL.startswith(('postgresql://', 'postgresql+asyncpg://')):
            raise HTTPException(503, 'Live billing requires a persistent PostgreSQL database')
        domains = await get(settings, 'checkout-domains', {'domain': expected.hostname, 'status': 'approved', 'per_page': 200})
        if not any(d.get('domain') == expected.hostname and d.get('status') == 'approved' for d in domains):
            raise HTTPException(503, 'The exact checkout hostname is not approved')
    hook = urlsplit(settings.PADDLE_WEBHOOK_URL)
    if (hook.scheme != 'https' or not hook.hostname or hook.username or hook.password
            or hook.query or hook.fragment or hook.path != '/api/payments/webhook/paddle'
            or (environment(settings) == 'production' and hook.hostname.endswith('trycloudflare.com'))):
        raise HTTPException(503, 'Configure a stable HTTPS PADDLE_WEBHOOK_URL')
    notifications = await get(settings, 'notification-settings')
    matches = [n for n in notifications if n.get('destination') == settings.PADDLE_WEBHOOK_URL and n.get('active')
        and n.get('traffic_source') in ('platform', 'all')]
    if len(matches) != 1:
        raise HTTPException(503, 'Exactly one active platform notification destination is required')
    notification = await get(settings, 'notification-settings/' + matches[0]['id'])
    from src.paddle_service import EVENTS
    subscribed = {e['name'] if isinstance(e, dict) else e for e in notification.get('subscribed_events', [])}
    if not set(EVENTS).issubset(subscribed):
        raise HTTPException(503, 'Paddle notification destination is missing required event types')
    import hmac
    if not hmac.compare_digest(notification.get('endpoint_secret_key', ''), settings.PADDLE_WEBHOOK_SECRET):
        raise HTTPException(503, 'Paddle webhook signing secret does not match destination')
