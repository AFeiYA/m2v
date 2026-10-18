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
    variant_id: str = Field(pattern=r'^\d{1,32}$')
    kind: Literal['topup', 'subscription']
    credits: int = Field(gt=0, le=1000000)
    price_cents: int = Field(gt=0, le=10000000)
    currency: Literal['USD'] = 'USD'


def configured():
    settings = get_settings()
    if not settings.BILLING_ENABLED:
        raise HTTPException(404, 'Billing is not enabled')
    if settings.LEMONSQUEEZY_TEST_MODE and not settings.BILLING_ALLOW_TEST_TRANSACTIONS:
        raise HTTPException(503, 'Test billing requires an explicitly isolated test deployment')
    unsupported=('MOTION_EXPORT_CREDITS','DRAFT_EXPORT_CREDITS','CLIP_EXPORT_CREDITS','SEPARATION_CREDITS')
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
        if len({p.id for p in products}) != len(products) or len({p.variant_id for p in products}) != len(products):
            raise ValueError()
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(503, 'Billing catalogue is invalid') from None
    return settings, {p.id:p for p in products}
