"""Read-only merchant configuration check; never creates a checkout or charge."""
import asyncio
from sqlalchemy import func, select
from src.billing_config import configured
from src.billing_models import BillingEvent
from src.billing_provider import validate_product
from src.database import async_session


async def check():
    settings,products=configured()
    for product in products.values():
        await validate_product(settings,product)
        print(f'Product {product.id}: provider configuration matches')
    async with async_session() as db:
        prefix=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
        pending=(await db.execute(select(func.count()).select_from(BillingEvent).where(
            BillingEvent.status=='pending',BillingEvent.resource_id.startswith(prefix)))).scalar_one()
    print(f'Environment: {"TEST" if settings.LEMONSQUEEZY_TEST_MODE else "LIVE"}; pending inbox: {pending}')
    print('Preflight passed. Checkout, renewal, refund and restore acceptance still required.')


if __name__=='__main__':
    try:
        asyncio.run(check())
    except Exception:
        print('Billing preflight failed. Check backend configuration, merchant products and database migration.')
        raise SystemExit(1) from None
