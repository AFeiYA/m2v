"""Lemon Squeezy transport. Provider errors never expose tokens or raw responses."""
import re
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException


async def request(settings, method, path, payload=None):
    if not re.fullmatch(r'(?:(checkouts|orders|subscriptions|subscription-invoices|variants|stores)(/[A-Za-z0-9-]+)?|prices\?filter\[variant_id\]=[0-9]{1,32})', path):
        raise ValueError('Invalid provider resource')
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(method, 'https://api.lemonsqueezy.com/v1/'+path,
                headers={'Authorization':'Bearer '+settings.LEMONSQUEEZY_API_KEY,
                         'Accept':'application/vnd.api+json','Content-Type':'application/vnd.api+json'},
                json=payload)
        if response.status_code >= 400:
            raise HTTPException(502, 'Billing provider unavailable. Please retry later.')
        data = response.json()['data']
        if path.startswith('prices?'):
            data = data[0] if isinstance(data,list) and data else None
        if not isinstance(data, dict) or not isinstance(data.get('attributes'), dict):
            raise ValueError('Invalid provider response')
        return data
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Billing provider unavailable. Please retry later.') from None


def safe_url(value, settings):
    if not isinstance(value, str) or len(value) > 2048:
        raise HTTPException(502, 'Invalid billing redirect')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise HTTPException(502, 'Invalid billing redirect') from None
    hosts = {h.strip().lower() for h in settings.LEMONSQUEEZY_ALLOWED_HOSTS.split(',') if h.strip()}
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or port not in (None,443):
        raise HTTPException(502, 'Invalid billing redirect')
    return value


async def validate_product(settings,product):
    store=await request(settings,'GET','stores/'+settings.LEMONSQUEEZY_STORE_ID)
    if store.get('type')!='stores' or str(store.get('id'))!=settings.LEMONSQUEEZY_STORE_ID or store['attributes'].get('currency')!=product.currency:
        raise HTTPException(503,'Billing store currency does not match catalogue')
    variant=await request(settings,'GET','variants/'+product.variant_id)
    va=variant['attributes']
    if variant.get('type')!='variants' or str(variant.get('id'))!=product.variant_id or va.get('test_mode') is not settings.LEMONSQUEEZY_TEST_MODE:
        raise HTTPException(503,'Billing variant environment does not match')
    price=await request(settings,'GET','prices?filter[variant_id]='+product.variant_id)
    a=price['attributes']
    category='subscription' if product.kind=='subscription' else 'one_time'
    if price.get('type')!='prices' or str(a.get('variant_id'))!=product.variant_id or a.get('category')!=category or a.get('scheme')!='standard' or a.get('usage_aggregation') or a.get('setup_fee_enabled') or a.get('unit_price')!=product.price_cents:
        raise HTTPException(503,'Billing price configuration does not match the provider')
    if product.kind=='subscription' and (a.get('renewal_interval_unit')!='month' or a.get('renewal_interval_quantity')!=1):
        raise HTTPException(503,'Subscription must be monthly')
