"""Transactional credit reservations and immutable balance history.

User.credits is the available balance. Reservations reduce it immediately;
settlement records successful delivery, release returns a failed reservation.
No payment/top-up endpoint is exposed here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update

from src.auth import get_current_user
from src.database import get_db
from src.models import CreditEntry, CreditReservation, User
from src.settings import get_settings
from src import credit_lots as lots

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
    return await lots.expire_available(db, uid, balance)


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


async def reserve(db, uid, operation_id, kind, amount, *, allow_reopen: bool = False):
    if amount < 0:
        raise ValueError("Credit cost must be nonnegative")
    balance = await lock_balance(db, uid)
    reservation_id = key(uid, kind, operation_id)
    reservation = await db.get(CreditReservation, reservation_id, populate_existing=True)
    if amount == 0 and reservation is None:
        return None
    await opening(db, uid, balance)
    if reservation and reservation.state == "held":
        return reservation
    if reservation and reservation.state == "settled" and not allow_reopen:
        return reservation
    # A retry preserves the original price; a reopen or new reservation uses amount.
    cost = amount if (allow_reopen or not reservation) else reservation.amount
    if balance < cost:
        raise HTTPException(403, f"Not enough credits. This operation requires {cost} credits.")
    balance -= cost
    await db.execute(update(User).where(User.id == uid).values(credits=balance))
    if reservation:
        reservation.state = "held"
        reservation.amount = cost
        reservation.attempt += 1
    else:
        reservation = CreditReservation(id=reservation_id, user_id=uid, operation_id=operation_id,
                                         kind=kind, amount=cost, state="held", attempt=1)
        db.add(reservation)
    await db.flush()
    await lots.allocate(db, reservation)
    labels = {
        "lyric_export": "Lyric video export",
        "motion_export": "Motion Studio export",
        "motion_webcodecs": "Motion Studio WebCodecs fast export",
        "separation": "Vocal separation",
        "alignment": "Lyrics alignment",
        "draft_export": "720p Draft export",
        "clip_export": "Excerpt clip export",
    }
    label = labels.get(kind, "Lyric video export" if kind == "lyric_export" else "Lyrics alignment")
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
    returned = 0 if success else await lots.release(db, reservation)
    if not success:
        balance += returned
        await db.execute(update(User).where(User.id == uid).values(credits=balance))
    reservation.state = "settled" if success else "released"
    labels = {
        "lyric_export": "Lyric video export",
        "motion_export": "Motion Studio export",
        "motion_webcodecs": "Motion Studio WebCodecs fast export",
        "separation": "Vocal separation",
        "alignment": "Lyrics alignment",
        "draft_export": "720p Draft export",
        "clip_export": "Excerpt clip export",
    }
    label = labels.get(kind, "Lyric video export" if kind == "lyric_export" else "Lyrics alignment")
    entry(db, reservation, event, returned, balance,
          label+(" · completed" if success else " · reserved credits returned")+
          (f" · {reservation.amount-returned} monthly credits expired" if not success and returned<reservation.amount else ""))
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


async def grant(db, uid, amount, reference, description="Credits added by administrator", *,
                lot_origin=None, expires_at=None, source_group=None, period_start=None):
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
    if lot_origin:
        await lots.add(db,uid,lot_origin,amount,expires_at,source_group,period_start)
    db.add(CreditEntry(id=event_id, user_id=uid, operation_id=reference, kind="account", event="grant",
                       amount=amount, balance_after=balance, description=description[:255]))
    await db.flush()
    await lots.expire_available(db,uid,balance)
    return True


async def check_monthly_quota_status(db, uid: str) -> dict:
    from src.models import UserPlan
    from src.billing_models import BillingSubscription
    settings = get_settings()
    user = await db.get(User, uid)
    now_utc = datetime.now(timezone.utc)
    month_key = f"{now_utc.year}-{now_utc.month:02d}"
    reference = f"free-monthly-{month_key}"
    event_id = key(uid, "grant", reference)
    claimed = bool(await db.get(CreditEntry, event_id))

    if not user or user.plan != UserPlan.FREE:
        return {
            "amount": settings.FREE_MONTHLY_QUOTA,
            "eligible": False,
            "claimed": claimed,
            "month": month_key,
        }

    active_sub = (await db.execute(
        select(BillingSubscription).where(
            BillingSubscription.user_id == uid,
            BillingSubscription.status.in_(("active", "on_trial", "paused"))
        )
    )).scalars().first()
    if active_sub:
        return {
            "amount": settings.FREE_MONTHLY_QUOTA,
            "eligible": False,
            "claimed": claimed,
            "month": month_key,
        }

    balance = user.credits
    wallet_info = await lots.wallet(db, uid, balance)
    permanent_available = wallet_info.get("permanent_available", 0)

    # 初始赠送积分消耗完毕后（永久积分小于每月配额），每月可领取一次免费额度
    eligible = (not claimed) and (permanent_available < settings.FREE_MONTHLY_QUOTA)
    return {
        "amount": settings.FREE_MONTHLY_QUOTA,
        "eligible": eligible,
        "claimed": claimed,
        "month": month_key,
        "permanent_available": permanent_available,
    }


async def replenish_free_quota(db, uid: str) -> dict:
    status = await check_monthly_quota_status(db, uid)
    if not status["eligible"]:
        reason = "already_claimed" if status["claimed"] else "has_permanent_credits"
        return {"granted": False, "reason": reason, **status}

    settings = get_settings()
    now_utc = datetime.now(timezone.utc)
    month_key = status["month"]
    origin = f"free-monthly-{uid}-{month_key}"
    reference = f"free-monthly-{month_key}"

    if now_utc.month == 12:
        end_of_month = now_utc.replace(year=now_utc.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        end_of_month = now_utc.replace(month=now_utc.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    amount = settings.FREE_MONTHLY_QUOTA
    description = f"Monthly free quota ({amount} credits)"
    success = await grant(
        db, uid, amount, reference, description=description,
        lot_origin=origin, expires_at=end_of_month, source_group="free_monthly", period_start=now_utc
    )
    if success:
        new_balance = await lock_balance(db, uid)
        return {
            "granted": True,
            "amount": amount,
            "balance": new_balance,
            "expires_at": end_of_month.isoformat(),
            "month": month_key,
        }
    return {"granted": False, "reason": "already_claimed", **status}


@router.post("/claim-monthly-quota")
async def claim_monthly_quota(user: User = Depends(get_current_user), db=Depends(get_db)):
    result = await replenish_free_quota(db, user.id)
    await db.commit()
    return result


@router.get("")
async def history(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                  user: User = Depends(get_current_user), db=Depends(get_db)):
    from src.export_jobs import reconcile
    from src.alignment_execution import reconcile as reconcile_alignment
    from src.motion_billing import reconcile as reconcile_motion
    await reconcile_motion(db,user.id)
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
    settings = get_settings()
    quota_status = await check_monthly_quota_status(db, user.id)
    return {"available": balance, "reserved": reserved, "entries": entries,
            "wallet": await lots.wallet(db,user.id,balance),
            "monthly_quota": quota_status,
            "total": total, "page": page, "page_size": page_size,
            "pricing": {
                "alignment": settings.ALIGNMENT_CREDITS,
                "separation": getattr(settings, "SEPARATION_CREDITS", 0),
                "lyric_export": settings.LYRIC_EXPORT_CREDITS,
                "motion_export": getattr(settings, "MOTION_EXPORT_CREDITS", 10),
                "motion_webcodecs": getattr(settings, "MOTION_WEBCODECS_CREDITS", 10),
                "draft_export": getattr(settings, "DRAFT_EXPORT_CREDITS", 0),
                "clip_export": getattr(settings, "CLIP_EXPORT_CREDITS", 0),
            }}
