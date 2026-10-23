"""Paddle transaction fulfillment on the shared credit ledger and durable inbox."""
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from src import credit_lots, credits, paddle_provider as provider
from src.billing_models import BillingCheckout, BillingEvent, BillingPayment, BillingSubscription
from src.billing_service import lock, reverse, utc
from src.paddle_config import PREFIX, STORE, scope

EVENTS = {
    **{name: 'transactions' for name in ('transaction.completed', 'transaction.payment_failed', 'transaction.past_due', 'transaction.canceled')},
    **{name: 'subscriptions' for name in ('subscription.created', 'subscription.activated', 'subscription.updated',
        'subscription.canceled', 'subscription.paused', 'subscription.resumed', 'subscription.past_due')},
    'adjustment.created': 'adjustments', 'adjustment.updated': 'adjustments',
}


def event_key(identifier):
    return hashlib.sha256(scope('event', identifier).encode()).hexdigest()


def verify_event(raw, signature, settings):
    try:
        parts = (signature or '').split(';')
        stamps = [p[3:] for p in parts if p.startswith('ts=')]
        digests = [p[3:] for p in parts if p.startswith('h1=')]
        if len(stamps) != 1 or not stamps[0].isdigit() or abs(time.time() - int(stamps[0])) > 5:
            raise ValueError()
        expected = hmac.new(settings.PADDLE_WEBHOOK_SECRET.encode(), stamps[0].encode() + b':' + raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, d) for d in digests if re.fullmatch(r'[a-f0-9]{64}', d)):
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict) or not re.fullmatch(r'evt_[a-z0-9]{26}', event.get('event_id', '')):
            raise ValueError()
        if not isinstance(event.get('event_type'), str) or not isinstance(event.get('data'), dict):
            raise ValueError()
        if not isinstance(event.get('occurred_at'), str) or not utc(event['occurred_at']):
            raise ValueError()
        return event
    except (ValueError, TypeError, KeyError, HTTPException):
        raise HTTPException(401, 'Paddle webhook could not be verified') from None


def check_items(data, intent):
    items = data.get('items') or []
    if (len(items) != 1 or items[0].get('quantity') != 1 or items[0].get('proration')
            or (items[0].get('price') or {}).get('id') != intent.variant_id
            or (items[0].get('price') or {}).get('unit_price') != {'amount': str(intent.price_cents), 'currency_code': intent.currency}):
        raise HTTPException(422, 'Paddle transaction or subscription price does not match Checkout')


async def fetch_transactions(settings, subscription_id):
    results, after = [], None
    for _ in range(20):
        payload = {'subscription_id': subscription_id, 'per_page': 100}
        if after:
            payload['after'] = after
        response = await provider.request(settings, 'GET', 'transactions', payload)
        rows = response.get('data')
        if not isinstance(rows, list):
            raise HTTPException(502, 'Invalid Paddle transaction list')
        results.extend(rows)
        if not (response.get('meta', {}).get('pagination') or {}).get('has_more'):
            return results
        if not rows or rows[-1]['id'] == after:
            break
        after = rows[-1]['id']
    raise HTTPException(503, 'Subscription history needs operator review')


async def find_intent(db, transaction=None, subscription=None, candidates=()):
    row = None
    if transaction:
        row = (await db.execute(select(BillingCheckout).where(
            BillingCheckout.provider_order_id == scope('txn', transaction['id'])))).scalar_one_or_none()
    if not row and subscription:
        sub = await db.get(BillingSubscription, scope('sub', subscription['id']), populate_existing=True)
        if sub:
            row = await db.get(BillingCheckout, sub.checkout_id, populate_existing=True)
        else:
            ids = [scope('txn', t['id']) for t in candidates if t.get('subscription_id') == subscription['id']]
            if ids:
                rows = (await db.execute(select(BillingCheckout).where(BillingCheckout.provider_order_id.in_(ids)))).scalars().all()
                if len(rows) == 1:
                    row = rows[0]
    if not row:
        raise HTTPException(503, 'Paddle purchase is not linked yet; retry required')
    if row.store_id != STORE or row.test_mode is not True:
        raise HTTPException(422, 'Paddle checkout environment does not match')
    return row


async def sync_subscription(db, data, intent):
    if intent.kind != 'subscription':
        raise HTTPException(422, 'Paddle subscription belongs to a one-time purchase')
    check_items(data, intent)
    if data.get('currency_code') != intent.currency or not re.fullmatch(r'ctm_[a-z0-9]{26}', data.get('customer_id', '')):
        raise HTTPException(422, 'Paddle subscription customer or currency does not match')
    sid = scope('sub', data['id'])
    row = await db.get(BillingSubscription, sid, populate_existing=True)
    updated = utc(data.get('updated_at'))
    if not updated:
        raise HTTPException(422, 'Paddle subscription timestamp is missing')
    if not row:
        row = BillingSubscription(id=sid, provider_id=data['id'], user_id=intent.user_id,
            checkout_id=intent.id, customer_id=data['customer_id'], variant_id=intent.variant_id,
            status='unknown', provider_updated_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
        db.add(row)
    if row.checkout_id != intent.id or row.customer_id != data['customer_id']:
        raise HTTPException(422, 'Paddle subscription identity changed')
    if updated >= utc(row.provider_updated_at):
        row.status = str(data.get('status', 'unknown'))[:24]
        row.renews_at = utc(data.get('next_billed_at'))
        scheduled = data.get('scheduled_change') or {}
        row.ends_at = utc(data.get('canceled_at') or (scheduled.get('effective_at') if scheduled.get('action') == 'cancel' else None))
        row.provider_updated_at = updated
    await db.flush()
    await credit_lots.cap_subscription(db, row.user_id, row.id, row.ends_at)
    return row


def amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,12}', value):
        raise HTTPException(422, 'Invalid Paddle amount')
    return int(value)


async def sync_payment(db, data, intent, subscription=None):
    check_items(data, intent)
    if data.get('status') != 'completed':
        if data.get('status') == 'canceled' and intent.state != 'paid':
            intent.state = 'expired'
        return
    if data.get('origin') not in ('api', 'subscription_recurring'):
        return  # Prorations, add-on charges, payment-method updates do not buy monthly credits.
    if (data.get('currency_code') != intent.currency or data.get('collection_mode') != 'automatic'
            or data.get('discount_id')):
        raise HTTPException(422, 'Unsupported Paddle payment currency, discount or collection mode')
    if bool(subscription) != (intent.kind == 'subscription'):
        raise HTTPException(422, 'Paddle subscription link is missing or unexpected')
    if subscription and data.get('customer_id') != subscription.customer_id:
        raise HTTPException(422, 'Paddle payment customer does not match')
    totals = (data.get('details') or {}).get('totals') or {}
    total = amount(totals.get('total'))
    if (total <= 0 or amount(totals.get('discount', '0')) or amount(totals.get('credit', '0'))
            or amount(totals.get('grand_total')) != total or totals.get('currency_code') != intent.currency):
        raise HTTPException(422, 'Unsupported Paddle transaction totals')
    expiry = start = None
    if subscription:
        period = data.get('billing_period') or {}
        start, expiry = utc(period.get('starts_at')), utc(period.get('ends_at'))
        if not start or not expiry or expiry <= start or (expiry - start).days > 32:
            raise HTTPException(422, 'Paddle monthly billing period is missing or invalid')
        if subscription.ends_at:
            expiry = min(expiry, utc(subscription.ends_at))
    pid = scope('txn', data['id'])
    row = await db.get(BillingPayment, pid, populate_existing=True)
    if not row:
        row = BillingPayment(id=pid, provider_id=data['id'], resource='transactions', user_id=intent.user_id,
            checkout_id=intent.id, subscription_id=subscription.id if subscription else None,
            billing_reason='renewal' if data.get('origin') == 'subscription_recurring' else 'initial',
            amount_cents=total, currency=intent.currency, credits=intent.credits,
            granted=False, revoked=0, refunded_cents=0, status='pending')
        db.add(row)
        await db.flush()
    if row.checkout_id != intent.id or row.amount_cents != total:
        raise HTTPException(409, 'Paddle payment identity changed')
    if not row.granted:
        await credits.grant(db, row.user_id, row.credits, 'paddle:' + row.id,
            ('Monthly credits' if subscription else 'Permanent credit pack') + ' · ' + intent.name,
            lot_origin=row.id, expires_at=expiry, source_group=subscription.id if subscription else None, period_start=start)
        row.granted = True
    refund = 0
    adjustments = data.get('adjustments')
    if not isinstance(adjustments, list) or len(adjustments) >= 100:
        raise HTTPException(503, 'Paddle adjustments could not be checked')
    seen = set()
    for adj in adjustments:
        if adj['id'] in seen:
            raise HTTPException(422, 'Duplicate Paddle adjustment')
        seen.add(adj['id'])
        if adj.get('status') == 'approved' and adj.get('action') in ('refund', 'credit', 'chargeback'):
            if adj.get('transaction_id') != data['id'] or adj.get('currency_code') != intent.currency:
                raise HTTPException(422, 'Paddle adjustment identity does not match')
            refund += amount((adj.get('totals') or {}).get('total'))
    if refund > total:
        raise HTTPException(422, 'Paddle adjustments exceed transaction total')
    row.refunded_cents = max(row.refunded_cents, refund)
    await reverse(db, row, (row.credits * row.refunded_cents + total - 1) // total)
    row.status = 'refunded' if row.revoked == row.credits else 'partial_refund' if row.revoked else 'paid'
    intent.state = 'paid'
    await db.flush()


async def process_inbox(db, eid, settings):
    event = await db.get(BillingEvent, eid, populate_existing=True)
    if not event or not event.resource_id.startswith(PREFIX):
        raise HTTPException(422, 'Paddle event environment does not match')
    if event.status in ('processed', 'review'):
        return False
    path = event.resource_id[len(PREFIX):]
    try:
        # Fetch before taking the mutation lock; webhook ingestion does no API calls.
        data = await provider.get(settings, path, {'include': 'adjustments'} if path.startswith('transactions/') else None)
        transaction = subscription = None
        candidates = []
        review = False
        if path.startswith('adjustments/'):
            review = data.get('action') not in ('refund', 'credit') or data.get('status') == 'reversed'
            transaction = await provider.get(settings, 'transactions/' + data['transaction_id'], {'include': 'adjustments'})
        elif path.startswith('transactions/'):
            transaction = data
        else:
            subscription = data
        if transaction and transaction.get('subscription_id'):
            subscription = await provider.get(settings, 'subscriptions/' + transaction['subscription_id'])
        if subscription:
            candidates = await fetch_transactions(settings, subscription['id'])
        await lock(db)
        event = await db.get(BillingEvent, eid, populate_existing=True)
        if event.status in ('processed', 'review'):
            return False
        intent = await find_intent(db, transaction, subscription, candidates)
        sub = await sync_subscription(db, subscription, intent) if subscription else None
        if transaction:
            await sync_payment(db, transaction, intent, sub)
        event.status = 'review' if review else 'processed'
        event.last_error = 'Paddle adjustment requires operator review' if review else None
        event.attempts += 1
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        await lock(db)
        event = await db.get(BillingEvent, eid, populate_existing=True)
        if event.status not in ('processed', 'review'):
            event.status = 'pending'
            event.attempts += 1
            event.last_error = 'Paddle synchronization failed; retry required'
        await db.commit()
        raise
