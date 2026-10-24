"""Trusted operator retry for durable billing inbox; no credentials or bodies logged.

Run against the configured billing deployment: python -m scripts.replay_billing_events
Use a scheduler every five minutes in production. Multiple workers are safe.
"""
import asyncio
import argparse
import re
from datetime import datetime, timezone
from sqlalchemy import select, or_
from src.billing_config import configured
from src.billing_models import BillingEvent
from src.billing_service import process_inbox
from src.database import async_session


async def replay(limit=100, *, event_id=None, include_review=False):
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
        from src.paddle_config import prefix as paddle_prefix
        prefix=paddle_prefix(settings)
    if event_id and not re.fullmatch(r'[a-f0-9]{64}', event_id):
        raise ValueError('Invalid event ID')
    if include_review and not event_id:
        raise ValueError('Review replay requires one explicit --event-id')
    async with async_session() as db:
        criteria = [BillingEvent.resource_id.startswith(prefix), BillingEvent.status.in_(
            ['pending', 'review'] if include_review else ['pending'])]
        if event_id:
            criteria.append(BillingEvent.id == event_id)
        else:
            criteria.append(or_(BillingEvent.next_attempt_at.is_(None),
                BillingEvent.next_attempt_at <= datetime.now(timezone.utc)))
        rows=(await db.execute(select(BillingEvent).where(*criteria)
            .order_by(BillingEvent.created_at).limit(limit))).scalars().all()
        ids = [row.id for row in rows]
        if include_review:
            for row in rows:
                row.status = 'pending'
            await db.commit()
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-id', help='Retry one event immediately, bypassing its delay')
    parser.add_argument('--include-review', action='store_true', help='After operator investigation, retry this one review event')
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(replay(event_id=args.event_id, include_review=args.include_review)) else 0)
