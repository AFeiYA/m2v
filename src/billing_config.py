"""Server-controlled catalogue; no client price, grant or return URL is trusted."""
import json
from typing import Literal
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from src.settings import get_settings


class Product(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    name: str = Field(min_length=1, max_length=128)
    variant_id: str = Field(pattern=r'^(?:\d{1,32}|price_[A-Za-z0-9]{1,56}|pri_[a-z0-9]{26})$')
    kind: Literal['topup', 'subscription']
    credits: int = Field(gt=0, le=1000000)
    price_cents: int = Field(gt=0, le=10000000)
    currency: Literal['USD'] = 'USD'


def configured():
    settings = get_settings()
    if not settings.BILLING_ENABLED:
        raise HTTPException(404, 'Billing is not enabled')
    if settings.BILLING_PROVIDER == 'paddle':
        from src.paddle_config import configured as paddle_configured
        return paddle_configured(settings)
    if settings.BILLING_PROVIDER == 'stripe':
        from src.stripe_config import configured as stripe_configured
        return stripe_configured(settings)
    if settings.BILLING_PROVIDER != 'lemonsqueezy':
        raise HTTPException(503, 'Unknown billing provider')
    if settings.LEMONSQUEEZY_TEST_MODE and not settings.BILLING_ALLOW_TEST_TRANSACTIONS:
        raise HTTPException(503, 'Test billing requires an explicitly isolated test deployment')
    unsupported=('DRAFT_EXPORT_CREDITS','CLIP_EXPORT_CREDITS','SEPARATION_CREDITS')
    if any(getattr(settings,name,0) for name in unsupported):
        raise HTTPException(503, 'Unsupported export pricing must remain zero until route-wide accounting is implemented')
    if not all([settings.LEMONSQUEEZY_API_KEY, settings.LEMONSQUEEZY_WEBHOOK_SECRET,
                settings.LEMONSQUEEZY_STORE_ID.isdigit(), settings.LEMONSQUEEZY_ALLOWED_HOSTS]):
        raise HTTPException(503, 'Billing setup is incomplete')
    site = urlsplit(settings.BILLING_SITE_URL)
    if site.scheme != 'https' or not site.hostname or site.username or site.password or site.query or site.fragment or site.path not in ('','/'):
        raise HTTPException(503, 'Billing return address is invalid')
    try:
        values = json.loads(settings.BILLING_PRODUCTS_JSON)
        if not isinstance(values,list) or not 1 <= len(values) <= 10:
            raise ValueError()
        products = [Product.model_validate(row) for row in values]
        if any(not p.variant_id.isdigit() for p in products):
            raise ValueError()
        expected_official = {('subscription', 999, 600), ('subscription', 2499, 2500), ('topup', 499, 200)}
        expected_fixture = {('subscription', 500, 1000), ('subscription', 1000, 2500), ('topup', 500, 500)}
        actual_catalog = {(p.kind, p.price_cents, p.credits) for p in products}
        # Legacy top-up rows are accepted for pending notifications/refunds only.
        if actual_catalog not in ({('subscription', 999, 300), ('subscription', 1999, 800), ('subscription', 2999, 1500)}, expected_official, expected_fixture,
                {p for p in expected_official if p[0] == 'subscription'},
                {p for p in expected_fixture if p[0] == 'subscription'}):
            raise ValueError()
        if len({p.id for p in products}) != len(products) or len({p.variant_id for p in products}) != len(products):
            raise ValueError()
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(503, 'Billing catalogue is invalid') from None
    return settings, {p.id:p for p in products}
