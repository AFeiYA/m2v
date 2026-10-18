"""Transactional credit reservations and immutable balance history.

User.credits is the available balance. Reservations reduce it immediately;
settlement records successful delivery, release returns a failed reservation.
No payment/top-up endpoint is exposed here.
"""
from __future__ import annotations

import hashlib
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update

from src.auth import get_current_user
from src.database import get_db
from src.models import CreditEntry, CreditReservation, User
from src.settings import get_settings

router = APIRouter(prefix="/api/credits", tags=["Credits"])


def key(*parts):
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()


async def lock_balance(db, uid):
    # A no-op UPDATE obtains the same row lock on PostgreSQL and the SQLite
    # write lock in local tests, before checking idempotency or the balance.
    balance = (await db.execute(update(User).where(User.id == uid)
                               .values(credits=User.credits).returning(User.credits))).scalar_one_or_none()
    if balance is None:
        raise HTTPException(404, "Account not found")
    return balance


async def opening(db, uid, balance=None):
    opening_id = key(uid, "opening")
    if await db.get(CreditEntry, opening_id):
        return
    if balance is None:
        balance = await lock_balance(db, uid)
        # Another first request may have created it while we waited for the lock.
        if await db.get(CreditEntry, opening_id):
            return
    db.add(CreditEntry(id=opening_id, user_id=uid, kind="account", event="opening",
                       amount=balance, balance_after=balance,
                       description="Starting balance (includes existing credits)"))
    await db.flush()


def entry(db, reservation, event, delta, balance, description):
    db.add(CreditEntry(id=key(reservation.id, reservation.attempt, event),
                       user_id=reservation.user_id, operation_id=reservation.operation_id,
                       kind=reservation.kind, event=event, amount=delta,
                       balance_after=balance, description=description))


async def reserve(db, uid, operation_id, kind, amount):
    if amount < 0:
        raise ValueError("Credit cost must be nonnegative")
    balance = await lock_balance(db, uid)
    reservation_id = key(uid, kind, operation_id)
    reservation = await db.get(CreditReservation, reservation_id, populate_existing=True)
    if amount == 0 and reservation is None:
        return None
    await opening(db, uid, balance)
    if reservation and reservation.state in ("held", "settled"):
        return reservation
    # A retry preserves the original price; a config change must not reprice it.
    cost = reservation.amount if reservation else amount
    if balance < cost:
        raise HTTPException(403, f"Not enough credits. This operation requires {cost} credits.")
    balance -= cost
    await db.execute(update(User).where(User.id == uid).values(credits=balance))
    if reservation:
        reservation.state = "held"
        reservation.attempt += 1
    else:
        reservation = CreditReservation(id=reservation_id, user_id=uid, operation_id=operation_id,
                                         kind=kind, amount=cost, state="held", attempt=1)
        db.add(reservation)
    label = "Lyric video export" if kind == "lyric_export" else ("Motion video export" if kind == "motion_export" else "Lyrics alignment")
    entry(db, reservation, "reserve", -cost, balance, label+" · credits reserved")
    await db.flush()
    return reservation


async def finish(db, uid, operation_id, kind, success):
    balance = await lock_balance(db, uid)
    reservation = await db.get(CreditReservation, key(uid, kind, operation_id), populate_existing=True)
    if not reservation or reservation.state != "held":
        return False
    await opening(db, uid, balance)
    event = "settle" if success else "release"
    if not success:
        balance += reservation.amount
        await db.execute(update(User).where(User.id == uid).values(credits=balance))
    reservation.state = "settled" if success else "released"
    label = "Lyric video export" if kind == "lyric_export" else ("Motion video export" if kind == "motion_export" else "Lyrics alignment")
    entry(db, reservation, event, 0 if success else reservation.amount, balance,
          label+(" · completed" if success else " · reserved credits returned"))
    await db.flush()
    return True



async def legacy_refund(db, uid, task_id, amount):
    """Preserve refunds for tasks reserved before ledger rollout, once only."""
    balance = await lock_balance(db, uid)
    await opening(db, uid, balance)
    event_id = key(uid, "legacy-refund", task_id)
    if await db.get(CreditEntry, event_id):
        return
    balance += amount
    await db.execute(update(User).where(User.id == uid).values(credits=balance))
    db.add(CreditEntry(id=event_id, user_id=uid, operation_id=task_id, kind="alignment",
                       event="release", amount=amount, balance_after=balance,
                       description="Earlier alignment task failed · credits returned"))
    await db.flush()


async def grant(db, uid, amount, reference, description="Credits added by administrator"):
    """Trusted server/CLI use only; never expose this as a public top-up API."""
    if amount <= 0 or not reference or len(reference) > 128:
        raise ValueError("A positive amount and a reference (1–128 characters) are required")
    balance = await lock_balance(db, uid)
    await opening(db, uid, balance)
    event_id = key(uid, "grant", reference)
    previous = await db.get(CreditEntry, event_id)
    if previous:
        if previous.amount != amount:
            raise HTTPException(409, "Reference already used for a different credit amount")
        return False
    balance += amount
    await db.execute(update(User).where(User.id == uid).values(credits=balance))
    db.add(CreditEntry(id=event_id, user_id=uid, operation_id=reference, kind="account", event="grant",
                       amount=amount, balance_after=balance, description=description[:255]))
    await db.flush()
    return True


@router.get("")
async def history(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                  user: User = Depends(get_current_user), db=Depends(get_db)):
    from src.export_jobs import reconcile
    from src.alignment_execution import reconcile as reconcile_alignment
    await reconcile_alignment(db, user.id)
    await reconcile(db, user.id)
    balance = await lock_balance(db, user.id)
    await opening(db, user.id, balance)
    reserved = (await db.execute(select(func.coalesce(func.sum(CreditReservation.amount), 0)).where(
        CreditReservation.user_id == user.id, CreditReservation.state == "held"))).scalar_one()
    total = (await db.execute(select(func.count()).select_from(CreditEntry).where(CreditEntry.user_id == user.id))).scalar_one()
    rows = (await db.execute(select(CreditEntry).where(CreditEntry.user_id == user.id).order_by(
        CreditEntry.created_at.desc(), CreditEntry.id.desc()).offset((page-1)*page_size).limit(page_size))).scalars()
    entries = []
    for row in rows:
        date = row.created_at
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        entries.append({"id": row.id, "event": row.event, "kind": row.kind,
                        "amount": row.amount, "balance_after": row.balance_after,
                        "description": row.description, "created_at": date.isoformat()})
    return {"available": balance, "reserved": reserved, "entries": entries,
            "total": total, "page": page, "page_size": page_size,
            "pricing": {"alignment": 1, "lyric_export": get_settings().LYRIC_EXPORT_CREDITS, "motion_export": get_settings().MOTION_EXPORT_CREDITS}}

