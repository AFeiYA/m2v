"""Validated Paddle environments and isolated resource identities."""
import json
import re
from urllib.parse import urlsplit
from fastapi import HTTPException
from src.billing_config import Product

def environment(settings):
    if settings.PADDLE_ENVIRONMENT not in ('sandbox', 'production'):
        raise HTTPException(503, 'Paddle environment must be sandbox or production')
    return settings.PADDLE_ENVIRONMENT


def store(settings=None):
    if settings is None:
        from src.settings import get_settings
        settings = get_settings()
    return 'paddle:' + environment(settings)


def prefix(settings=None):
    return store(settings) + ':'



def api_key(settings):
    return settings.PADDLE_API_KEY or (settings.PADDLE_SANDBOX_API_KEY if environment(settings) == 'sandbox' else '')


def scope(resource, identifier, settings=None):
    return prefix(settings) + resource + ':' + identifier


def configured(settings):
    mode = environment(settings)
    sandbox = mode == 'sandbox'
    if sandbox and not settings.BILLING_ALLOW_TEST_TRANSACTIONS:
        raise HTTPException(503, 'Paddle sandbox requires an explicitly isolated test deployment')
    if not sandbox and (not settings.PADDLE_LIVE_ENABLED or settings.BILLING_ALLOW_TEST_TRANSACTIONS):
        raise HTTPException(503, 'Live Paddle requires explicit activation and test billing disabled')
    if (not api_key(settings).startswith('pdl_sdbx_' if sandbox else 'pdl_live_') or not settings.PADDLE_CLIENT_TOKEN.startswith('test_' if sandbox else 'live_')
            or not settings.PADDLE_WEBHOOK_SECRET):
        raise HTTPException(503, 'Paddle credentials do not match the selected environment')
    site = urlsplit(settings.BILLING_SITE_URL)
    local = sandbox and site.hostname in ('localhost', '127.0.0.1') and site.scheme == 'http'
    if (not site.hostname or (site.scheme != 'https' and not local) or site.username or site.password
            or site.path not in ('', '/') or site.query or site.fragment):
        raise HTTPException(503, 'Invalid Paddle return URL')
    if any(getattr(settings, name, 0) for name in ('DRAFT_EXPORT_CREDITS', 'CLIP_EXPORT_CREDITS', 'SEPARATION_CREDITS')):
        raise HTTPException(503, 'Unsupported export surcharges must remain zero')
    try:
        raw = json.loads(settings.BILLING_PRODUCTS_JSON)
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError()
        products = [Product.model_validate(p) for p in raw]
        if (len({p.id for p in products}) != 3 or len({p.variant_id for p in products}) != 3
                or any(not re.fullmatch(r'pri_[a-z0-9]{26}', p.variant_id) for p in products)
                or {(p.kind, p.price_cents, p.credits) for p in products}
                != {('topup', 499, 200), ('subscription', 999, 600), ('subscription', 2499, 2500)}):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(503, 'Invalid Paddle catalogue') from None
    return settings, {p.id: p for p in products}
