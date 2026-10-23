"""Stripe SDK transport. No secret, raw error or customer payload is logged."""
import re
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from src.stripe_config import API_VERSION


async def request(settings, method, path, payload=None, *, key=None):
    import stripe
    if not re.fullmatch(r'(?:account|prices/price_[A-Za-z0-9]+|checkout/sessions(?:/cs_[A-Za-z0-9_]+(?:/line_items)?)?|subscriptions/sub_[A-Za-z0-9]+|invoices/in_[A-Za-z0-9]+|charges(?:/ch_[A-Za-z0-9]+)?|payment_intents/pi_[A-Za-z0-9]+|invoice_payments|billing_portal/(?:sessions|configurations/bpc_[A-Za-z0-9]+)|tax/(?:settings|registrations)|disputes/dp_[A-Za-z0-9]+|radar/early_fraud_warnings/issfr_[A-Za-z0-9]+)', path):
        raise ValueError('Invalid Stripe resource')
    transport = stripe.HTTPXClient(timeout=20)
    client = stripe.StripeClient(settings.STRIPE_API_KEY, stripe_version=API_VERSION,
        max_network_retries=2, http_client=transport)
    try:
        response = await client.raw_request_async(method, '/v1/' + path,
            **(payload or {}), **({'idempotency_key': key} if key else {}))
        data = response.data
        if not isinstance(data, dict):
            raise ValueError()
        if 'livemode' in data and data['livemode'] is not False:
            raise HTTPException(422, 'Stripe environment does not match')
        return data
    except (stripe.StripeError, httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Stripe is temporarily unavailable. Please retry later.') from None
    finally:
        await transport.close_async()


def safe_url(value, *, receipt=False):
    try:
        p = urlsplit(value) if isinstance(value, str) and len(value) <= 2048 else None
        allowed = {'checkout.stripe.com', 'billing.stripe.com'}
        if receipt:
            allowed |= {'invoice.stripe.com', 'pay.stripe.com', 'payments.stripe.com'}
        if (not p or p.scheme != 'https' or p.hostname not in allowed or p.username
                or p.password or p.port not in (None, 443)):
            raise ValueError()
    except ValueError:
        raise HTTPException(502, 'Invalid Stripe redirect') from None
    return value


async def validate_product(settings, product):
    price = await request(settings, 'get', 'prices/' + product.variant_id, {'expand': ['product']})
    recurring = price.get('recurring')
    if (price.get('id') != product.variant_id or price.get('livemode') is not False
            or price.get('active') is not True or price.get('currency') != product.currency.lower()
            or price.get('unit_amount') != product.price_cents or price.get('billing_scheme') != 'per_unit'
            or price.get('transform_quantity') or price.get('custom_unit_amount')
            or (product.kind == 'topup' and recurring)
            or (product.kind == 'subscription' and (not recurring or recurring.get('interval') != 'month'
                or recurring.get('interval_count') != 1 or recurring.get('usage_type') != 'licensed'))):
        raise HTTPException(503, 'Stripe price does not match the server catalogue')
    if settings.STRIPE_AUTOMATIC_TAX:
        product_data = price.get('product')
        if not isinstance(product_data, dict) or not product_data.get('tax_code') or price.get('tax_behavior') not in ('exclusive', 'inclusive'):
            raise HTTPException(503, 'Stripe product tax code and price tax behavior are required')
    return price


async def preflight(settings, products):
    account = await request(settings, 'get', 'account')
    if account.get('id') != settings.STRIPE_ACCOUNT_ID:
        raise HTTPException(503, 'Stripe API key belongs to a different account')
    prices = [await validate_product(settings, product) for product in products.values()]
    product_ids = [p['product']['id'] if isinstance(p.get('product'), dict) else p.get('product') for p in prices]
    if len(set(product_ids)) != len(prices):
        raise HTTPException(503, 'Each Stripe package needs a separate Product')
    await validate_portal(settings)
    if settings.STRIPE_AUTOMATIC_TAX:
        tax = await request(settings, 'get', 'tax/settings')
        registrations = await request(settings, 'get', 'tax/registrations', {'status': 'active', 'limit': 1})
        if tax.get('status') != 'active' or not registrations.get('data'):
            raise HTTPException(503, 'Stripe Tax requires active settings and a registration')


async def validate_portal(settings):
    identifier = settings.STRIPE_PORTAL_CONFIGURATION_ID
    if not re.fullmatch(r'bpc_[A-Za-z0-9]+', identifier):
        raise HTTPException(503, 'Stripe portal configuration is required')
    config = await request(settings, 'get', 'billing_portal/configurations/' + identifier)
    features = config.get('features') or {}
    if (config.get('active') is not True or (features.get('subscription_update') or {}).get('enabled')
            or (features.get('subscription_cancel') or {}).get('mode') != 'at_period_end'
            or not (features.get('subscription_cancel') or {}).get('enabled')):
        raise HTTPException(503, 'Stripe portal must disable plan changes and cancel at period end')
    return identifier
