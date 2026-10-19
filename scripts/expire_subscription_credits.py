"""Expire due available subscription credits; safe across concurrent replicas.

Read/spend paths enforce expiration even if this optional sweep is delayed.
"""
import asyncio
from sqlalchemy import select
from src.credit_lots import CreditLot, now
from src.credits import lock_balance
from src.database import async_session


async def expire_due(limit=1000):
    async with async_session() as db:
        uids=(await db.execute(select(CreditLot.user_id).where(CreditLot.remaining>0,
            CreditLot.expires_at.is_not(None),CreditLot.expires_at<=now()).distinct().limit(limit))).scalars().all()
    for uid in uids:
        async with async_session() as db:
            await lock_balance(db,uid)
            await db.commit()
    return len(uids)


if __name__=='__main__':
    print(f'Subscription expiry sweep: {asyncio.run(expire_due())} accounts checked')
