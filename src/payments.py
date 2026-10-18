"""Payment checkout, verified/idempotent callbacks, grants, refunds, and order history."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from src.auth import get_current_user, get_current_user_flexible
from src.database import get_db
from src.models import OrderStatus, PaymentOrder, User
from src.settings import get_settings

router = APIRouter(prefix="/api/payments", tags=["Payments"])

PACKAGES = {
    "starter": {
        "id": "starter",
        "name": "Starter Pack",
        "credits": 20,
        "amount_cents": 499,
        "currency": "USD",
        "description": "20 export credits for casual music creators",
    },
    "creator": {
        "id": "creator",
        "name": "Creator Pack",
        "credits": 60,
        "amount_cents": 1299,
        "currency": "USD",
        "description": "60 export credits for regular video creators",
    },
    "studio": {
        "id": "studio",
        "name": "Studio Pack",
        "credits": 200,
        "amount_cents": 3999,
        "currency": "USD",
        "description": "200 export credits for power users and music studios",
    },
}


def now():
    return datetime.now(timezone.utc)


class CheckoutRequest(BaseModel):
    package_id: str
    provider: Literal["mock", "stripe", "alipay", "wechat"] = "mock"
    idempotency_key: str | None = Field(default=None, max_length=128)


class RefundRequest(BaseModel):
    reason: str = Field(default="Customer request", max_length=255)


def verify_signature(secret: str, payload_bytes: bytes, signature: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.get("/packages")
async def list_packages():
    """List available top-up credit packages with pricing details."""
    return {
        "packages": list(PACKAGES.values()),
        "pricing_live": False,
        "billing_status": "beta_preview",
        "notice": "Billing is currently in beta preview; video exports do not incur live credit charges.",
    }


@router.post("/checkout")
async def create_checkout(req: CheckoutRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Create a checkout session/order with strict idempotency."""
    pkg = PACKAGES.get(req.package_id)
    if not pkg:
        raise HTTPException(400, f"Invalid package_id '{req.package_id}'. Available: {list(PACKAGES.keys())}")

    # Idempotency check: if the client provided an idempotency key, return existing order
    if req.idempotency_key:
        existing = (await db.execute(select(PaymentOrder).where(
            PaymentOrder.idempotency_key == req.idempotency_key
        ))).scalar_one_or_none()
        if existing:
            if existing.user_id != user.id:
                raise HTTPException(409, "Idempotency key belongs to another account")
            return {
                "order_id": existing.id,
                "status": existing.status,
                "package_id": existing.package_id,
                "credits": existing.credits,
                "amount_cents": existing.amount_cents,
                "currency": existing.currency,
                "provider": existing.provider,
                "checkout_url": f"/api/payments/checkout-session/{existing.id}",
                "reused": True,
            }

    order_id = f"ord_{uuid.uuid4().hex[:24]}"
    order = PaymentOrder(
        id=order_id,
        user_id=user.id,
        package_id=pkg["id"],
        credits=pkg["credits"],
        amount_cents=pkg["amount_cents"],
        currency=pkg["currency"],
        provider=req.provider,
        idempotency_key=req.idempotency_key,
        status=OrderStatus.PENDING.value,
        details={"package_name": pkg["name"]},
    )
    db.add(order)
    await db.commit()

    return {
        "order_id": order_id,
        "status": order.status,
        "package_id": order.package_id,
        "credits": order.credits,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "provider": order.provider,
        "checkout_url": f"/api/payments/checkout-session/{order_id}",
        "reused": False,
    }


@router.post("/webhook/{provider}")
async def payment_webhook(
    provider: str,
    request: Request,
    x_webhook_signature: str | None = Header(None, alias="X-Webhook-Signature"),
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
    db=Depends(get_db),
):
    """Verified, idempotent payment callback. Grants credits atomically upon payment."""
    settings = get_settings()
    body_bytes = await request.body()

    # Signature/secret verification
    authorized = False
    if x_webhook_secret:
        authorized = (x_webhook_secret == settings.PAYMENT_WEBHOOK_SECRET)
    elif x_webhook_signature:
        authorized = verify_signature(settings.PAYMENT_WEBHOOK_SECRET, body_bytes, x_webhook_signature)
    elif provider == "mock" and settings.PAYMENT_WEBHOOK_SECRET == "payment-dev-webhook-secret":
        # In dev/test mode with default secret and no signature headers passed, allow mock provider callback
        authorized = True


    if not authorized:
        raise HTTPException(401, "Invalid webhook signature or secret")

    try:
        data = json.loads(body_bytes.decode()) if body_bytes else {}
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    order_id = data.get("order_id") or data.get("client_reference_id")
    event_type = data.get("event") or data.get("type", "payment.succeeded")

    if not order_id:
        raise HTTPException(400, "Missing order_id in webhook payload")

    order = (await db.execute(select(PaymentOrder).where(
        PaymentOrder.id == order_id
    ).with_for_update())).scalar_one_or_none()

    if not order:
        raise HTTPException(404, f"Order '{order_id}' not found")

    # Idempotent handling: already paid
    if order.status == OrderStatus.PAID.value:
        return {
            "status": "already_paid",
            "order_id": order.id,
            "credits": order.credits,
            "message": "Webhook processed previously (idempotent)",
        }

    if event_type in ("payment.succeeded", "checkout.session.completed"):
        order.status = OrderStatus.PAID.value
        order.paid_at = now()
        order.provider_order_id = data.get("provider_order_id") or data.get("payment_intent")
        order.details = {**(order.details or {}), "webhook_payload": data}

        from src.credits import grant
        await grant(
            db,
            order.user_id,
            order.credits,
            reference=f"order:{order.id}",
            description=f"Payment for {order.package_id} (+{order.credits} credits)",
        )
        await db.commit()

        return {
            "status": "paid",
            "order_id": order.id,
            "credits_granted": order.credits,
            "message": "Payment verified and credits granted successfully",
        }
    elif event_type in ("payment.failed", "checkout.session.expired"):
        order.status = OrderStatus.FAILED.value
        order.details = {**(order.details or {}), "failure_reason": data.get("error", "Payment failed or expired")}
        await db.commit()
        return {"status": "failed", "order_id": order.id}
    else:
        return {"status": "ignored", "event": event_type}


@router.post("/mock-complete/{order_id}")
async def mock_complete_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Sandbox/Testing endpoint: mark order paid and grant credits.
    Strictly disabled in production; requires M2V_ALLOW_MOCK_PAYMENTS=true and user ownership.
    """
    import os
    if os.getenv("M2V_ALLOW_MOCK_PAYMENTS", "").strip().lower() not in ("1", "true", "yes"):
        raise HTTPException(404, "Mock payment completion is disabled in this environment")

    order = (await db.execute(select(PaymentOrder).where(
        PaymentOrder.id == order_id
    ).with_for_update())).scalar_one_or_none()

    if not order:
        raise HTTPException(404, "Order not found")

    if order.user_id != user.id:
        raise HTTPException(403, "Cannot complete order belonging to another user")

    if order.status == OrderStatus.PAID.value:
        return {"status": "already_paid", "order_id": order.id, "credits": order.credits}

    order.status = OrderStatus.PAID.value
    order.paid_at = now()
    from src.credits import grant
    await grant(
        db,
        order.user_id,
        order.credits,
        reference=f"order:{order.id}",
        description=f"Sandbox Payment for {order.package_id} (+{order.credits} credits)",
    )
    await db.commit()
    return {"status": "paid", "order_id": order.id, "credits_granted": order.credits}


@router.post("/orders/{order_id}/refund")
async def refund_order(
    order_id: str,
    req: RefundRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Refund a paid order and deduct previously granted credits with ledger entry."""
    order = (await db.execute(select(PaymentOrder).where(
        PaymentOrder.id == order_id
    ).with_for_update())).scalar_one_or_none()

    if not order:
        raise HTTPException(404, "Order not found")

    # Strict owner check: only the order owner can request a refund
    if order.user_id != user.id:
        raise HTTPException(403, "Cannot refund an order owned by another user")

    if order.status != OrderStatus.PAID.value:
        raise HTTPException(400, f"Cannot refund order with status '{order.status}'. Must be 'paid'.")

    order.status = OrderStatus.REFUNDED.value
    order.refunded_at = now()
    order.details = {**(order.details or {}), "refund_reason": req.reason}

    from src.credits import lock_balance, opening
    from src.models import CreditEntry
    balance = await lock_balance(db, user.id)
    await opening(db, user.id, balance)

    deduct = min(order.credits, balance)  # deduct available credits up to the granted amount
    new_balance = balance - deduct
    await db.execute(update(User).where(User.id == user.id).values(credits=new_balance))

    event_id = hashlib.sha256(f"{user.id}:refund:{order.id}".encode()).hexdigest()
    db.add(CreditEntry(
        id=event_id,
        user_id=user.id,
        operation_id=order.id,
        kind="payment",
        event="refund",
        amount=-deduct,
        balance_after=new_balance,
        description=f"Order {order.id} refunded ({req.reason})"[:255],
    ))
    await db.commit()

    return {
        "status": "refunded",
        "order_id": order.id,
        "deducted_credits": deduct,
        "new_balance": new_balance,
    }


@router.get("/orders")
async def list_user_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user_flexible),
    db=Depends(get_db),
):
    """List authenticated user's payment order history (strictly owner isolated)."""
    total = (await db.execute(select(func.count()).select_from(PaymentOrder).where(
        PaymentOrder.user_id == user.id
    ))).scalar_one()

    rows = (await db.execute(select(PaymentOrder).where(
        PaymentOrder.user_id == user.id
    ).order_by(PaymentOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()

    orders = []
    for r in rows:
        created = r.created_at.replace(tzinfo=timezone.utc) if r.created_at and r.created_at.tzinfo is None else r.created_at
        paid = r.paid_at.replace(tzinfo=timezone.utc) if r.paid_at and r.paid_at.tzinfo is None else r.paid_at
        refunded = r.refunded_at.replace(tzinfo=timezone.utc) if r.refunded_at and r.refunded_at.tzinfo is None else r.refunded_at

        orders.append({
            "id": r.id,
            "package_id": r.package_id,
            "credits": r.credits,
            "amount_cents": r.amount_cents,
            "currency": r.currency,
            "status": r.status,
            "provider": r.provider,
            "created_at": created.isoformat() if created else None,
            "paid_at": paid.isoformat() if paid else None,
            "refunded_at": refunded.isoformat() if refunded else None,
        })

    return {
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
