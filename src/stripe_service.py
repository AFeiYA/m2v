"""Resolve Stripe ownership through Checkout/Subscription IDs, then use the credit ledger.

Only minimal resource IDs are persisted. Replaying an event fetches current Stripe
state, so duplicate and out-of-order deliveries cannot mint a second allocation.
"""
import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from src import credits, credit_lots, stripe_provider as provider
from src.billing_models import BillingCheckout, BillingSubscription, BillingPayment, BillingEvent
from src.billing_service import lock, reverse
from src.stripe_config import API_VERSION, scope, store

EVENTS = {
    'checkout.session.completed': 'checkout/sessions',
    'checkout.session.async_payment_succeeded': 'checkout/sessions',
    'checkout.session.async_payment_failed': 'checkout/sessions',
    'checkout.session.expired': 'checkout/sessions',
    'customer.subscription.created': 'subscriptions',
    'customer.subscription.updated': 'subscriptions',
    'customer.subscription.deleted': 'subscriptions',
    'customer.subscription.paused': 'subscriptions',
    'customer.subscription.resumed': 'subscriptions',
    'invoice.paid': 'invoices',
    'invoice.payment_failed': 'invoices',
    'invoice.finalization_failed': 'invoices',
    'charge.refunded': 'charges',
    'charge.dispute.created': 'disputes',
    'radar.early_fraud_warning.created': 'radar/early_fraud_warnings',
}


def identity(value):
    return value.get('id') if isinstance(value, dict) else value


def timestamp(value):
    if type(value) is not int or value <= 0:
        raise HTTPException(422, 'Missing Stripe period boundary')
    return datetime.fromtimestamp(value, timezone.utc)


def sandbox(data):
    if data.get('livemode') is not False:
        raise HTTPException(422, 'Stripe environment does not match')
    return data


async def single_list(settings, path, params):
    data = await provider.request(settings, 'get', path, {**params, 'limit': 100})
    if not isinstance(data.get('data'), list) or data.get('has_more'):
        raise HTTPException(503, 'Stripe resource requires billing review')
    return data['data']


async def intent_for_session(db, settings, session):
    sandbox(session)
    row = (await db.execute(select(BillingCheckout).where(
        BillingCheckout.provider_order_id == scope(settings, 'session', session['id'])))).scalar_one_or_none()
    if not row:
        raise HTTPException(503, 'Stripe Checkout is not linked yet; retry this event')
    if row.store_id != store(settings) or row.test_mode is not True:
        raise HTTPException(422, 'Stripe Checkout environment does not match')
    lines = await single_list(settings, 'checkout/sessions/' + session['id'] + '/line_items', {})
    expected_mode = 'subscription' if row.kind == 'subscription' else 'payment'
    if (session.get('mode') != expected_mode or len(lines) != 1 or lines[0].get('quantity') != 1
            or identity(lines[0].get('price')) != row.variant_id
            or session.get('currency') != row.currency.lower()
            or session.get('amount_subtotal') != row.price_cents
            or (session.get('total_details') or {}).get('amount_discount', 0)):
        raise HTTPException(422, 'Stripe Checkout product or amount does not match')
    return row


async def session_for_subscription(settings, identifier):
    rows = await single_list(settings, 'checkout/sessions', {'subscription': identifier})
    if len(rows) != 1:
        raise HTTPException(503, 'Stripe subscription Checkout is not linked yet')
    return sandbox(rows[0])


async def sync_subscription(db, settings, data):
    sandbox(data)
    session = await session_for_subscription(settings, data['id'])
    intent = await intent_for_session(db, settings, session)
    customer = identity(data.get('customer'))
    items = (data.get('items') or {}).get('data', [])
    if (intent.kind != 'subscription' or not customer or identity(session.get('customer')) != customer
            or len(items) != 1 or (data.get('items') or {}).get('has_more')
            or identity(items[0].get('price')) != intent.variant_id or items[0].get('quantity') != 1):
        raise HTTPException(422, 'Stripe subscription identity or tier changed; review required')
    sid = scope(settings, 'sub', data['id'])
    row = await db.get(BillingSubscription, sid, populate_existing=True)
    if not row:
        row = BillingSubscription(id=sid, provider_id=data['id'], user_id=intent.user_id,
            checkout_id=intent.id, customer_id=customer, variant_id=intent.variant_id,
            status='unknown', provider_updated_at=datetime.now(timezone.utc))
        db.add(row)
    if row.checkout_id != intent.id or row.customer_id != customer:
        raise HTTPException(422, 'Stripe subscription owner changed')
    row.status = str(data.get('status', 'unknown'))[:24]
    row.renews_at = timestamp(items[0]['current_period_end']) if items[0].get('current_period_end') else None
    end = data.get('ended_at') or data.get('cancel_at')
    if not end and data.get('cancel_at_period_end'):
        end = items[0].get('current_period_end')
    row.ends_at = timestamp(end) if end else None
    row.provider_updated_at = datetime.now(timezone.utc)
    await db.flush()
    await credit_lots.cap_subscription(db, row.user_id, row.id, row.ends_at)
    return row, intent


async def refunds_for_intent(settings, identifier):
    charges = await single_list(settings, 'charges', {'payment_intent': identifier})
    total = refunded = 0
    for charge in charges:
        sandbox(charge)
        if charge.get('paid') and charge.get('captured'):
            amount = charge.get('amount_captured')
            refund = charge.get('amount_refunded', 0)
            if type(amount) is not int or type(refund) is not int or not 0 <= refund <= amount:
                raise HTTPException(422, 'Invalid Stripe charge totals')
            total += amount
            refunded += refund
    return total, refunded


async def invoice_refunds(settings, invoice):
    payments = await single_list(settings, 'invoice_payments', {'invoice': invoice['id'], 'status': 'paid'})
    total = refunded = 0
    seen = set()
    for payment in payments:
        pi = identity((payment.get('payment') or {}).get('payment_intent'))
        if not pi or pi in seen:
            raise HTTPException(503, 'Unsupported Stripe invoice payment; review required')
        seen.add(pi)
        captured, reversed_amount = await refunds_for_intent(settings, pi)
        total += captured
        refunded += reversed_amount
    return total, refunded


async def sync_payment(db, settings, data, intent, subscription=None):
    sandbox(data)
    invoice = subscription is not None
    resource = 'invoices' if invoice else 'checkout/sessions'
    paid = data.get('status') == 'paid' if invoice else data.get('payment_status') == 'paid' and data.get('status') == 'complete'
    if not paid:
        if not invoice and data.get('status') == 'expired' and intent.state != 'paid':
            intent.state = 'expired'
        return
    start = expiry = None
    if invoice:
        if data.get('billing_reason') not in ('subscription_create', 'subscription_cycle'):
            return  # Prorations/manual invoices never buy a fresh monthly allocation.
        lines = (data.get('lines') or {}).get('data', [])
        if len(lines) != 1 or (data.get('lines') or {}).get('has_more'):
            raise HTTPException(422, 'Unsupported Stripe invoice lines')
        line = lines[0]
        detail = (line.get('parent') or {}).get('subscription_item_details') or {}
        if (identity((line.get('pricing') or {}).get('price_details', {}).get('price')) != intent.variant_id
                or line.get('quantity') != 1 or line.get('amount') != intent.price_cents or detail.get('proration')):
            raise HTTPException(422, 'Stripe invoice price does not match Checkout')
        start, expiry = timestamp(line['period']['start']), timestamp(line['period']['end'])
        if expiry <= start or (expiry - start).days > 32:
            raise HTTPException(422, 'Invalid Stripe monthly period')
        if subscription.ends_at:
            expiry = min(expiry, subscription.ends_at.replace(tzinfo=timezone.utc) if subscription.ends_at.tzinfo is None else subscription.ends_at)
        total = data.get('total')
        if data.get('amount_paid') != total or data.get('subtotal') != intent.price_cents:
            raise HTTPException(422, 'Stripe invoice is not fully paid at the agreed price')
        captured, refunded = await invoice_refunds(settings, data)
    else:
        total = data.get('amount_total')
        pi = identity(data.get('payment_intent'))
        if not pi:
            raise HTTPException(422, 'Stripe payment intent is missing')
        captured, refunded = await refunds_for_intent(settings, pi)
    if (type(total) is not int or total <= 0 or captured != total or not 0 <= refunded <= total
            or data.get('currency') != intent.currency.lower()):
        raise HTTPException(422, 'Stripe payment totals or currency do not match')
    pid = scope(settings, 'invoice' if invoice else 'session', data['id'])
    row = await db.get(BillingPayment, pid, populate_existing=True)
    if not row:
        row = BillingPayment(id=pid, resource=resource, provider_id=data['id'], user_id=intent.user_id,
            checkout_id=intent.id, subscription_id=subscription.id if invoice else None,
            billing_reason=('initial' if data.get('billing_reason') == 'subscription_create' else 'renewal') if invoice else None,
            amount_cents=total, currency=intent.currency, credits=intent.credits,
            granted=False, revoked=0, refunded_cents=0, status='pending')
        db.add(row)
        await db.flush()
    if row.checkout_id != intent.id or row.amount_cents != total:
        raise HTTPException(409, 'Stripe payment identity changed')
    if not row.granted:
        await credits.grant(db, row.user_id, row.credits, 'stripe:' + row.id,
            ('Monthly credits' if invoice else 'Permanent credit pack') + ' · ' + intent.name,
            lot_origin=row.id, expires_at=expiry, source_group=subscription.id if invoice else None,
            period_start=start)
        row.granted = True
    row.refunded_cents = max(row.refunded_cents, refunded)
    await reverse(db, row, (row.credits * row.refunded_cents + total - 1) // total)
    row.status = 'refunded' if row.revoked == row.credits else 'partial_refund' if row.revoked else 'paid'
    intent.state = 'paid'
    await db.flush()


async def apply_invoice(db, settings, data):
    parent = (data.get('parent') or {}).get('subscription_details') or {}
    sub_id = identity(parent.get('subscription'))
    if not sub_id:
        return  # One-time Checkout invoice is informational; its Session owns the grant.
    remote = await provider.request(settings, 'get', 'subscriptions/' + sub_id)
    subscription, intent = await sync_subscription(db, settings, remote)
    if identity(data.get('customer')) != subscription.customer_id:
        raise HTTPException(422, 'Stripe invoice customer does not match')
    await sync_payment(db, settings, data, intent, subscription)


async def apply_charge(db, settings, charge):
    sandbox(charge)
    pi = identity(charge.get('payment_intent'))
    if not pi:
        raise HTTPException(503, 'Stripe charge cannot be traced; review required')
    invoices = await single_list(settings, 'invoice_payments', {'payment': {'type': 'payment_intent', 'payment_intent': pi}})
    if invoices:
        for payment in invoices:
            invoice = await provider.request(settings, 'get', 'invoices/' + identity(payment['invoice']))
            await apply_invoice(db, settings, invoice)
    else:
        sessions = await single_list(settings, 'checkout/sessions', {'payment_intent': pi})
        if len(sessions) != 1 or sessions[0].get('mode') != 'payment':
            raise HTTPException(503, 'Stripe payment Checkout cannot be traced')
        session = sessions[0]
        intent = await intent_for_session(db, settings, session)
        await sync_payment(db, settings, session, intent)


async def process_inbox(db, event_id, settings):
    event = await db.get(BillingEvent, event_id, populate_existing=True)
    if not event or not event.resource_id.startswith(f'stripe:0:{settings.STRIPE_ACCOUNT_ID}:'):
        raise HTTPException(422, 'Stripe event environment does not match')
    if event.status in ('processed', 'review'):
        return False
    path = event.resource_id.split(':', 3)[3]
    try:
        await lock(db)  # Serialize fresh provider reads with account mutations across replicas.
        event = await db.get(BillingEvent, event_id, populate_existing=True)
        if event.status in ('processed', 'review'):
            return False
        data = sandbox(await provider.request(settings, 'get', path))
        if path.startswith('checkout/sessions/'):
            intent = await intent_for_session(db, settings, data)
            if intent.kind == 'topup':
                await sync_payment(db, settings, data, intent)
            elif identity(data.get('subscription')):
                remote = await provider.request(settings, 'get', 'subscriptions/' + identity(data['subscription']))
                await sync_subscription(db, settings, remote)
        elif path.startswith('subscriptions/'):
            await sync_subscription(db, settings, data)
        elif path.startswith('invoices/'):
            await apply_invoice(db, settings, data)
        elif path.startswith('charges/'):
            await apply_charge(db, settings, data)
        else:
            charge_id = identity(data.get('charge'))
            if charge_id:
                charge = await provider.request(settings, 'get', 'charges/' + charge_id)
                await apply_charge(db, settings, charge)
            event.status = 'review'
            event.last_error = 'Dispute or fraud warning requires operator review in Stripe Workbench'
        if event.status != 'review':
            event.status = 'processed'
            event.last_error = None
        event.attempts += 1
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        await lock(db)
        event = await db.get(BillingEvent, event_id, populate_existing=True)
        if event.status not in ('processed', 'review'):
            event.status = 'pending'
            event.attempts += 1
            event.last_error = 'Stripe synchronization failed; retry required'
        await db.commit()
        raise


def verify_event(raw, signature, settings):
    import stripe
    try:
        event = stripe.Webhook.construct_event(raw, signature or '', settings.STRIPE_WEBHOOK_SECRET, tolerance=300).to_dict()
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(401, 'Invalid Stripe webhook signature') from None
    sandbox(event)
    if event.get('account') not in (None, settings.STRIPE_ACCOUNT_ID):
        raise HTTPException(422, 'Stripe webhook account does not match')
    if event.get('api_version') != API_VERSION:
        raise HTTPException(422, 'Stripe webhook API version does not match')
    return event


def event_key(settings, identifier):
    return hashlib.sha256(scope(settings, 'event', identifier).encode()).hexdigest()
