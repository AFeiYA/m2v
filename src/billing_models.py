"""Additive billing tables. Never store cards, webhook bodies or portal tokens."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base
from src.models import _now


class BillingMutex(Base):
    __tablename__ = 'billing_mutex'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)


class BillingCheckout(Base):
    __tablename__ = 'billing_checkouts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    product_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(24))
    variant_id: Mapped[str] = mapped_column(String(64))
    credits: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    test_mode: Mapped[bool] = mapped_column(Boolean)
    store_id: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default='creating')
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    order_total_cents: Mapped[int | None] = mapped_column(Integer,nullable=True)
    order_refunded_cents: Mapped[int] = mapped_column(Integer,default=0)
    provider_order_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingSubscription(Base):
    __tablename__ = 'billing_subscriptions'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    checkout_id: Mapped[str] = mapped_column(ForeignKey('billing_checkouts.id'), unique=True)
    customer_id: Mapped[str] = mapped_column(String(64))
    variant_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingPayment(Base):
    __tablename__ = 'billing_payments'
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    checkout_id: Mapped[str] = mapped_column(ForeignKey('billing_checkouts.id'), index=True)
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey('billing_subscriptions.id'), nullable=True)
    billing_reason: Mapped[str | None] = mapped_column(String(16),nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    credits: Mapped[int] = mapped_column(Integer)
    granted: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[int] = mapped_column(Integer, default=0)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BillingEvent(Base):
    __tablename__ = 'billing_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(64))
    routing_checkout_id: Mapped[str | None] = mapped_column(ForeignKey('billing_checkouts.id'),nullable=True)
    status: Mapped[str] = mapped_column(String(16),default='pending')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(128),nullable=True)
    resource_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
