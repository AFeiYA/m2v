"""Trusted operator retry for durable billing inbox; no credentials or bodies logged.

Run against the configured billing deployment: python -m scripts.replay_billing_events
Use a scheduler every five minutes in production. Multiple workers are safe.
"""
import asyncio
from sqlalchemy import select
from src.billing_config import configured
from src.billing_models import BillingEvent
from src.billing_service import process_inbox
from src.database import async_session


async def replay(limit=100):
    settings,_=configured()
    from scripts.expire_subscription_credits import expire_due
    await expire_due()
    processor=process_inbox
    prefix=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
    if settings.BILLING_PROVIDER=='stripe':
        from src.stripe_service import process_inbox as processor
        prefix=f'stripe:0:{settings.STRIPE_ACCOUNT_ID}:'
    elif settings.BILLING_PROVIDER=='paddle':
        from src.paddle_service import process_inbox as processor
        from src.paddle_config import PREFIX as prefix
    async with async_session() as db:
        ids=(await db.execute(select(BillingEvent.id).where(BillingEvent.status=='pending',
            BillingEvent.resource_id.startswith(prefix)).order_by(BillingEvent.created_at).limit(limit))).scalars().all()
    completed=failed=0
    for identifier in ids:
        async with async_session() as db:
            try:
                completed+=int(await processor(db,identifier,settings))
            except Exception:
                failed+=1
    print(f'Billing replay: processed={completed}, pending={failed}')
    return failed


if __name__=='__main__':
    raise SystemExit(1 if asyncio.run(replay()) else 0)
