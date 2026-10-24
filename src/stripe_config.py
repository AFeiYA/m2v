"""Sandbox-only rollout: require an explicitly isolated test deployment."""
import json
import re
from urllib.parse import urlsplit
from fastapi import HTTPException
from src.billing_config import Product

API_VERSION = '2026-09-30.endive'


def configured(settings):
    if not settings.STRIPE_TEST_MODE:
        raise HTTPException(503, 'Live Stripe billing is not enabled in this release')
    if not settings.BILLING_ALLOW_TEST_TRANSACTIONS:
        raise HTTPException(503, 'Stripe sandbox requires an isolated test deployment')
    if (not re.fullmatch(r'(?:rk|sk)_test_[A-Za-z0-9_]+', settings.STRIPE_API_KEY)
            or not settings.STRIPE_WEBHOOK_SECRET.startswith('whsec_')
            or not re.fullmatch(r'acct_[A-Za-z0-9]+', settings.STRIPE_ACCOUNT_ID)):
        raise HTTPException(503, 'Stripe sandbox credentials are incomplete')
    site = urlsplit(settings.BILLING_SITE_URL)
    if (site.scheme != 'https' or not site.hostname or site.username or site.password
            or site.query or site.fragment or site.path not in ('', '/')):
        raise HTTPException(503, 'Billing return address is invalid')
    if any(getattr(settings, name, 0) for name in ('DRAFT_EXPORT_CREDITS', 'CLIP_EXPORT_CREDITS', 'SEPARATION_CREDITS')):
        raise HTTPException(503, 'Unsupported export pricing must remain zero')
    try:
        raw = json.loads(settings.BILLING_PRODUCTS_JSON)
        if not isinstance(raw, list) or len(raw) not in (2, 3):
            raise ValueError()
        products = [Product.model_validate(p) for p in raw]
        if ({(p.kind, p.price_cents, p.credits) for p in products}
                not in ({('subscription', 999, 300), ('subscription', 1999, 800), ('subscription', 2999, 1500)},
                           {('subscription', 999, 600), ('subscription', 2499, 2500)},
                           {('topup', 499, 200), ('subscription', 999, 600), ('subscription', 2499, 2500)})):
            raise ValueError()
        if (len({p.id for p in products}) != len(products) or len({p.variant_id for p in products}) != len(products)
                or any(not p.variant_id.startswith('price_') for p in products)):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(503, 'Stripe catalogue is invalid') from None
    return settings, {p.id: p for p in products}


def scope(settings, resource='', identifier=''):
    return f'stripe:0:{settings.STRIPE_ACCOUNT_ID}:{resource}:{identifier}'


def store(settings):
    return 'stripe:' + settings.STRIPE_ACCOUNT_ID
