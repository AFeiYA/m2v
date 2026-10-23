"""Paddle adapter for the existing billing UI. All fulfillment is asynchronous."""
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from src import credits, paddle_provider as provider, paddle_service as service
from src.billing_config import configured
from src.billing_models import BillingCheckout, BillingEvent, BillingPayment, BillingSubscription
from src.billing_service import lock, utc
from src.database import async_session, get_db
from src.paddle_config import PREFIX, STORE, scope

router = APIRouter()
log = logging.getLogger('m2v')


def now():
    return datetime.now(timezone.utc)


def checkout_view(row, settings, customer_id=None):
    if row.state == 'paid':
        return {'checkout_id': row.id, 'state': 'paid', 'url': None}
    if row.state in ('creating', 'failed'):
        raise HTTPException(409, 'Checkout is not ready. Refresh billing before trying again.')
    if row.state == 'expired' or utc(row.expires_at) <= now():
        raise HTTPException(410, 'Checkout expired. Start a new checkout.')
    return {'provider': 'paddle', 'checkout_id': row.id, 'state': row.state,
        'transaction_id': row.provider_order_id.rsplit(':', 1)[-1], 'environment': 'sandbox',
        'client_token': settings.PADDLE_CLIENT_TOKEN, 'customer_id': customer_id,
        'success_url': settings.BILLING_SITE_URL.rstrip('/') + '/app?checkout=' + row.id + '#credits-section'}


async def checkout(req, user, db, settings, products):
    product = products.get(req.product_id)
    if not product:
        raise HTTPException(400, 'Unknown billing product')
    eid = credits.key('paddle-checkout', STORE, user.id, req.idempotency_key)
    await lock(db)
    row = await db.get(BillingCheckout, eid, populate_existing=True)
    if row:
        if row.user_id != user.id or row.store_id != STORE or row.product_id != product.id or (
                row.state != 'paid' and (row.variant_id, row.price_cents, row.credits) != (product.variant_id, product.price_cents, product.credits)):
            raise HTTPException(409, 'Checkout key belongs to a different package or price')
        return checkout_view(row, settings)
    if product.kind == 'subscription':
        subs = (await db.execute(select(BillingSubscription).where(BillingSubscription.user_id == user.id))).scalars()
        if any(s.status not in ('canceled', 'expired', 'incomplete_expired') and (not s.ends_at or utc(s.ends_at) > now()) for s in subs):
            raise HTTPException(409, 'You already have a subscription. Manage it in the billing portal.')
    pending = (await db.execute(select(BillingCheckout).where(BillingCheckout.user_id == user.id,
        BillingCheckout.store_id == STORE, BillingCheckout.state.in_(['creating', 'open']), BillingCheckout.expires_at > now(),
        BillingCheckout.kind == 'subscription' if product.kind == 'subscription' else BillingCheckout.product_id == product.id))).scalars().first()
    if pending:
        if (pending.product_id, pending.variant_id, pending.price_cents, pending.credits) != (product.id, product.variant_id, product.price_cents, product.credits):
            raise HTTPException(409, 'An earlier Checkout is still open. Finish it or wait for expiry.')
        return checkout_view(pending, settings)
    count = (await db.execute(select(func.count()).select_from(BillingCheckout).where(
        BillingCheckout.user_id == user.id, BillingCheckout.created_at > now() - timedelta(hours=1)))).scalar_one()
    if count >= 10:
        raise HTTPException(429, 'Too many checkout attempts. Please try later.')
    row = BillingCheckout(id=eid, user_id=user.id, product_id=product.id, name=product.name, kind=product.kind,
        variant_id=product.variant_id, credits=product.credits, price_cents=product.price_cents, currency=product.currency,
        test_mode=True, store_id=STORE, nonce=secrets.token_hex(24), state='creating', expires_at=now() + timedelta(minutes=45))
    db.add(row)
    await db.commit()
    try:
        await provider.preflight(settings, products)
        result = await provider.request(settings, 'POST', 'transactions', {
            'items': [{'price_id': product.variant_id, 'quantity': 1}], 'currency_code': product.currency,
            'collection_mode': 'automatic', 'custom_data': {'checkout_id': row.id, 'user_id': row.user_id, 'nonce': row.nonce}})
        remote = result['data']
        if not re.fullmatch(r'txn_[a-z0-9]{26}', remote.get('id', '')):
            raise HTTPException(502, 'Invalid Paddle transaction response')
        service.check_items(remote, row)
        await lock(db)
        row = await db.get(BillingCheckout, eid, populate_existing=True)
        row.provider_order_id = scope('txn', remote['id'])
        if row.state == 'creating':
            row.state = 'open'
        await db.commit()
        return checkout_view(row, settings)
    except Exception:
        await db.rollback()
        await lock(db)
        row = await db.get(BillingCheckout, eid, populate_existing=True)
        if row.state == 'creating':
            row.state = 'failed'
        await db.commit()
        raise


async def background(eid, settings):
    try:
        async with async_session() as db:
            await service.process_inbox(db, eid, settings)
    except Exception:
        log.warning('Paddle event remains pending; operator replay required: %s', eid)


@router.post('/webhook/paddle')
async def webhook(request: Request, background_tasks: BackgroundTasks,
        paddle_signature: str | None = Header(None, alias='Paddle-Signature'), db=Depends(get_db)):
    settings, _ = configured()
    if settings.BILLING_PROVIDER != 'paddle':
        raise HTTPException(404, 'Paddle billing is not enabled')
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > 262144:
            raise HTTPException(413, 'Paddle event is too large')
    event = service.verify_event(bytes(body), paddle_signature, settings)
    kind = service.EVENTS.get(event['event_type'])
    if not kind:
        return {'received': True, 'ignored': True}
    identifier = event['data'].get('id', '')
    expected = {'transactions': 'txn', 'subscriptions': 'sub', 'adjustments': 'adj'}[kind]
    if not re.fullmatch(expected + r'_[a-z0-9]{26}', identifier):
        raise HTTPException(400, 'Invalid Paddle resource ID')
    eid = service.event_key(event['event_id'])
    resource = PREFIX + kind + '/' + identifier
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    await db.execute(insert(BillingEvent).values(id=eid, event_name=event['event_type'], resource_id=resource,
        status='pending', attempts=0).on_conflict_do_nothing())
    stored = await db.get(BillingEvent, eid, populate_existing=True)
    if stored.resource_id != resource or stored.event_name != event['event_type']:
        raise HTTPException(409, 'Paddle event identity changed')
    await db.commit()  # Acknowledge only after a durable commit; no external calls above.
    if stored.status == 'pending':
        background_tasks.add_task(background, eid, settings)
    return {'received': True, 'queued': stored.status == 'pending'}


async def status(user, db, settings):
    rows = (await db.execute(select(BillingSubscription).where(BillingSubscription.user_id == user.id,
        BillingSubscription.id.startswith(PREFIX)).order_by(BillingSubscription.provider_updated_at.desc()))).scalars().all()
    return {'test_mode': True, 'customer_id': rows[0].customer_id if rows else None,
        'subscriptions': [{'id': s.id, 'status': s.status, 'renews_at': s.renews_at, 'ends_at': s.ends_at} for s in rows]}


async def orders(user, db, settings, page, page_size):
    criteria = (BillingPayment.user_id == user.id, BillingPayment.id.startswith(PREFIX))
    total = (await db.execute(select(func.count()).select_from(BillingPayment).where(*criteria))).scalar_one()
    rows = (await db.execute(select(BillingPayment).where(*criteria).order_by(BillingPayment.created_at.desc(), BillingPayment.id)
        .offset((page - 1) * page_size).limit(page_size))).scalars()
    return {'orders': [{'id': p.id, 'status': p.status, 'amount_cents': p.amount_cents, 'currency': p.currency,
        'credits': p.credits if p.granted else 0, 'credits_reversed': p.revoked,
        'refunded_cents': p.refunded_cents, 'created_at': p.created_at} for p in rows],
        'total': total, 'page': page, 'page_size': page_size}


async def checkout_status(identifier, user, db, settings):
    row = await db.get(BillingCheckout, identifier)
    if not row or row.user_id != user.id or row.store_id != STORE:
        raise HTTPException(404, 'Checkout not found')
    rows = (await db.execute(select(BillingPayment).where(BillingPayment.checkout_id == row.id,
        BillingPayment.granted.is_(True)))).scalars().all()
    confirmed = any(p.credits > p.revoked for p in rows)
    return {'checkout_id': row.id, 'state': 'refunded' if rows and not confirmed else row.state, 'credits_confirmed': confirmed}


async def customer_portal(settings, customer_id, subscription_ids=None):
    if not re.fullmatch(r'ctm_[a-z0-9]{26}', customer_id or ''):
        raise HTTPException(404, 'Paddle customer is not available yet')
    result = await provider.request(settings, 'POST', 'customers/' + customer_id + '/portal-sessions',
        {'subscription_ids': subscription_ids or []})
    return {'url': provider.safe_url(result['data']['urls']['general']['overview'])}


async def portal(identifier, user, db, settings):
    row = await db.get(BillingSubscription, identifier)
    if not row or row.user_id != user.id or not row.id.startswith(PREFIX):
        raise HTTPException(404, 'Subscription not found')
    return await customer_portal(settings, row.customer_id, [row.provider_id])


async def receipt(identifier, user, db, settings):
    row = await db.get(BillingPayment, identifier)
    if not row or row.user_id != user.id or not row.id.startswith(PREFIX):
        raise HTTPException(404, 'Payment not found')
    transaction = await provider.get(settings, 'transactions/' + row.provider_id)
    return await customer_portal(settings, transaction.get('customer_id'))


async def reconcile(user, db, settings):
    # Scope every source to the signed-in owner, then retry a bounded set of resources.
    rows = (await db.execute(select(BillingCheckout).where(BillingCheckout.user_id == user.id,
        BillingCheckout.store_id == STORE, BillingCheckout.provider_order_id.is_not(None))
        .order_by(BillingCheckout.created_at.desc()).limit(20))).scalars().all()
    for row in rows:
        transaction_id = row.provider_order_id.rsplit(':', 1)[-1]
        eid = credits.key('paddle-reconcile', row.id, now().strftime('%Y%m%d%H%M'))
        existing = await db.get(BillingEvent, eid)
        if not existing:
            db.add(BillingEvent(id=eid, event_name='transaction.completed', resource_id=PREFIX + 'transactions/' + transaction_id,
                status='pending', attempts=0))
            await db.commit()
        await service.process_inbox(db, eid, settings)
    return {'checked': len(rows), 'notice': 'New renewals require webhook delivery or operator inbox replay.'}
