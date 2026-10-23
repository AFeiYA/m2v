"""Bounded Paddle Billing REST client for the existing Python backend."""
import re
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from src.paddle_config import api_key

BASE = 'https://sandbox-api.paddle.com'


async def request(settings, method, path, payload=None):
    if settings.PADDLE_ENVIRONMENT != 'sandbox' or not api_key(settings).startswith('pdl_sdbx_'):
        raise HTTPException(503, 'Only Paddle sandbox credentials are accepted')
    if not re.fullmatch(r'(?:transactions(?:/txn_[a-z0-9]{26}(?:/invoice)?)?|subscriptions/sub_[a-z0-9]{26}|adjustments/adj_[a-z0-9]{26}|prices/pri_[a-z0-9]{26}|customers/ctm_[a-z0-9]{26}/portal-sessions|settings/checkout-url)', path):
        raise ValueError('Invalid Paddle resource')
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.request(method, BASE + '/' + path,
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


def safe_url(value, *, invoice=False):
    try:
        p = urlsplit(value) if isinstance(value, str) and len(value) <= 4096 else None
        hosts = {'sandbox-customer-portal.paddle.com'}
        # Invoice API returns a short-lived signed link on Paddle's document host.
        if invoice:
            hosts |= {'sandbox-invoices.paddle.com', 'sandbox-buy.paddle.com', 'invoices.paddle.com'}
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
            or price.get('trial_period') or price.get('unit_price_overrides')
            or quantity.get('minimum') != 1 or quantity.get('maximum') != 1
            or (product.kind == 'topup' and cycle is not None)
            or (product.kind == 'subscription' and cycle != {'interval': 'month', 'frequency': 1})):
        raise HTTPException(503, 'Paddle price does not match the server catalogue')
    return price


async def preflight(settings, products):
    prices = [await validate_product(settings, p) for p in products.values()]
    if len({p.get('product_id') for p in prices}) != len(prices):
        raise HTTPException(503, 'Use a separate Paddle Product for each package')
    checkout = await get(settings, 'settings/checkout-url')
    if not checkout.get('default_url'):
        raise HTTPException(503, 'Set the Paddle sandbox default payment link first')
