"""Credit provenance: expiring subscription lots, permanent packs and held usage.

User.credits remains the net available balance. Legacy/admin credits form the
implicit permanent remainder; existing balances are never retroactively expired.
All mutations run while the caller holds credits.lock_balance's user-row lock.
"""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, select, update
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base
from src.models import CreditEntry, User


class CreditLot(Base):
    __tablename__='credit_lots'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id'),index=True)
    origin: Mapped[str]=mapped_column(String(128),unique=True)
    amount: Mapped[int]=mapped_column(Integer)
    remaining: Mapped[int]=mapped_column(Integer)
    expired: Mapped[int]=mapped_column(Integer,default=0)
    refunded: Mapped[int]=mapped_column(Integer,default=0)
    expires_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    source_group: Mapped[str | None]=mapped_column(String(128),nullable=True,index=True)
    period_start: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)


class CreditAllocation(Base):
    __tablename__='credit_allocations'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    reservation_id: Mapped[str]=mapped_column(ForeignKey('credit_reservations.id'),index=True)
    attempt: Mapped[int]=mapped_column(Integer)
    lot_id: Mapped[str]=mapped_column(ForeignKey('credit_lots.id'),index=True)
    amount: Mapped[int]=mapped_column(Integer)


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def expire_available(db,uid,balance):
    from src import credits
    rows=(await db.execute(select(CreditLot).where(CreditLot.user_id==uid,
        CreditLot.expires_at.is_not(None),CreditLot.expires_at<=now(),CreditLot.remaining>0)
        .order_by(CreditLot.expires_at,CreditLot.id).execution_options(populate_existing=True))).scalars().all()
    for lot in rows:
        await credits.opening(db,uid,balance)
        amount=lot.remaining;lot.remaining=0;lot.expired+=amount;balance-=amount
        db.add(CreditEntry(id=credits.key(lot.id,'expiry',lot.expired),user_id=uid,
            operation_id=lot.origin,kind='subscription',event='expire',amount=-amount,
            balance_after=balance,description='Unused monthly subscription credits expired'))
    if rows:
        await db.execute(update(User).where(User.id==uid).values(credits=balance))
        await db.flush()
    return balance


async def add(db,uid,origin,amount,expires_at=None,source_group=None,period_start=None):
    from src import credits
    identifier=credits.key('credit-lot',uid,origin)
    existing=await db.get(CreditLot,identifier,populate_existing=True)
    if existing:
        if existing.amount!=amount or existing.user_id!=uid:
            raise ValueError('Credit lot identity changed')
        return existing
    if source_group and period_start:
        period_start=utc(period_start)
        siblings=(await db.execute(select(CreditLot).where(CreditLot.user_id==uid,
            CreditLot.source_group==source_group,CreditLot.period_start.is_not(None))
            .execution_options(populate_existing=True))).scalars().all()
        for previous in siblings:
            start=utc(previous.period_start)
            if start<period_start and (previous.expires_at is None or utc(previous.expires_at)>period_start):
                previous.expires_at=period_start
            elif start>period_start and (expires_at is None or utc(expires_at)>start):
                expires_at=start  # An old invoice cannot reopen an already ended period.
    lot=CreditLot(id=identifier,user_id=uid,origin=origin,amount=amount,remaining=amount,
        expired=0,refunded=0,expires_at=expires_at,source_group=source_group,period_start=period_start)
    db.add(lot);await db.flush()
    return lot


async def allocate(db,reservation):
    """Consume soonest-expiring lots first; legacy permanent balance is the fallback."""
    from src import credits
    rows=(await db.execute(select(CreditLot).where(CreditLot.user_id==reservation.user_id,
        CreditLot.remaining>0).order_by(CreditLot.expires_at.asc().nulls_last(),CreditLot.id)
        .execution_options(populate_existing=True))).scalars().all()
    remaining=reservation.amount
    for lot in rows:
        amount=min(remaining,lot.remaining)
        if amount:
            lot.remaining-=amount;remaining-=amount
            db.add(CreditAllocation(id=credits.key(reservation.id,reservation.attempt,lot.id),
                reservation_id=reservation.id,attempt=reservation.attempt,lot_id=lot.id,amount=amount))
        if remaining==0:
            break
    await db.flush()


async def release(db,reservation):
    """Expired held credits cannot be laundered into a new period by failing a job."""
    allocations=(await db.execute(select(CreditAllocation).where(
        CreditAllocation.reservation_id==reservation.id,CreditAllocation.attempt==reservation.attempt)
        .order_by(CreditAllocation.id))).scalars().all()
    returned=reservation.amount-sum(a.amount for a in allocations)  # Legacy permanent portion.
    for allocation in allocations:
        lot=await db.get(CreditLot,allocation.lot_id,populate_existing=True)
        capacity=max(0,lot.amount-lot.refunded-lot.expired-lot.remaining)
        unrevoked=min(allocation.amount,capacity)
        if lot.expires_at is not None and utc(lot.expires_at)<=now():
            lot.expired+=unrevoked
            returned+=allocation.amount-unrevoked  # Return only previously reversed debt.
        else:
            lot.remaining+=unrevoked
            returned+=allocation.amount
    await db.flush()
    return returned


async def revoke(db,uid,origin,previous_target,target):
    """Return the net new debit; already expired credits are never debited twice."""
    from src import credits
    lot=await db.get(CreditLot,credits.key('credit-lot',uid,origin),populate_existing=True)
    if not lot:  # Preserve financial treatment of grants preceding lot accounting.
        return target-previous_target
    unexpired_total=max(0,lot.amount-lot.expired)
    debit=max(0,min(target,unexpired_total)-min(previous_target,unexpired_total))
    lot.remaining-=min(debit,lot.remaining)
    lot.refunded=max(lot.refunded,target)
    await db.flush()
    return debit


async def cap_subscription(db,uid,source_group,ends_at):
    if not ends_at:
        return
    from src import credits
    balance=await credits.lock_balance(db,uid)  # User first, then lots: same order as spending.
    rows=(await db.execute(select(CreditLot).where(CreditLot.user_id==uid,
        CreditLot.source_group==source_group).execution_options(populate_existing=True))).scalars().all()
    for lot in rows:
        if lot.expires_at is not None and utc(lot.expires_at)>utc(ends_at):
            lot.expires_at=ends_at
    await db.flush()
    await expire_available(db,uid,balance)


async def wallet(db,uid,balance):
    lots=(await db.execute(select(CreditLot).where(CreditLot.user_id==uid,
        CreditLot.expires_at.is_not(None),CreditLot.expires_at>now(),CreditLot.remaining>0))).scalars().all()
    subscription=min(max(balance,0),sum(lot.remaining for lot in lots))
    return {'subscription_available':subscription,'permanent_available':max(0,balance-subscription),
        'debt':max(0,-balance),'next_expiry':min((utc(lot.expires_at) for lot in lots),default=None)}
