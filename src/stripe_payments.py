"""Stripe adapter behind the existing authenticated /api/payments UI contract."""
import secrets
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from src import credits, stripe_provider as provider, stripe_service as service
from src.billing_config import configured
from src.billing_models import BillingCheckout, BillingEvent, BillingPayment, BillingSubscription
from src.billing_service import lock, utc
from src.database import get_db
from src.stripe_config import scope, store

router = APIRouter()


def now():
    return datetime.now(timezone.utc)


def prefix(settings):
    return f'stripe:0:{settings.STRIPE_ACCOUNT_ID}:'


def owned_checkout(row, user, settings):
    if not row or row.user_id != user.id or row.store_id != store(settings) or row.test_mode is not True:
        raise HTTPException(404, 'Checkout not found')
    return row


def view(row):
    if row.state == 'paid':
        return {'checkout_id': row.id, 'state': 'paid', 'url': None}
    if row.state in ('creating', 'failed'):
        raise HTTPException(409, 'Checkout is not ready. Refresh billing before starting a new checkout.')
    if row.state == 'expired' or utc(row.expires_at) <= now():
        raise HTTPException(410, 'Checkout expired. Start a new checkout.')
    return {'checkout_id': row.id, 'state': row.state, 'url': provider.safe_url(row.url)}


async def checkout(req, user, db, settings, products):
    product = products.get(req.product_id)
    if not product:
        raise HTTPException(400, 'Unknown billing product')
    identifier = credits.key('stripe-checkout', settings.STRIPE_ACCOUNT_ID, user.id, req.idempotency_key)
    await lock(db)
    row = await db.get(BillingCheckout, identifier, populate_existing=True)
    if row:
        owned_checkout(row, user, settings)
        if row.product_id != product.id or (row.state != 'paid' and (row.credits, row.price_cents, row.variant_id) != (product.credits, product.price_cents, product.variant_id)):
            raise HTTPException(409, 'Checkout key belongs to a different product or price')
        return view(row)
    if product.kind == 'subscription':
        existing = (await db.execute(select(BillingSubscription).where(
            BillingSubscription.user_id == user.id))).scalars().all()
        # Block an existing subscription on either provider while migrating.
        if any(s.status not in ('expired', 'canceled', 'incomplete_expired') and (not s.ends_at or utc(s.ends_at) > now()) for s in existing):
            raise HTTPException(409, 'You already have a subscription. Manage it in the billing portal.')
    pending = (await db.execute(select(BillingCheckout).where(
        BillingCheckout.user_id == user.id, BillingCheckout.store_id == store(settings),
        BillingCheckout.kind == 'subscription' if product.kind == 'subscription' else BillingCheckout.product_id == product.id,
        BillingCheckout.state.in_(['creating', 'open']), BillingCheckout.expires_at > now()))).scalars().first()
    if pending:
        if pending.product_id != product.id or (pending.price_cents, pending.credits, pending.variant_id) != (product.price_cents, product.credits, product.variant_id):
            raise HTTPException(409, 'An earlier checkout is still open. Finish it or wait for it to expire.')
        return view(pending)
    count = (await db.execute(select(func.count()).select_from(BillingCheckout).where(
        BillingCheckout.user_id == user.id, BillingCheckout.created_at > now() - timedelta(hours=1)))).scalar_one()
    if count >= 10:
        raise HTTPException(429, 'Too many checkout attempts. Try again later.')
    row = BillingCheckout(id=identifier, user_id=user.id, product_id=product.id, name=product.name,
        kind=product.kind, variant_id=product.variant_id, credits=product.credits, price_cents=product.price_cents,
        currency=product.currency, test_mode=True, store_id=store(settings), nonce=secrets.token_hex(24),
        state='creating', expires_at=now() + timedelta(minutes=45))
    db.add(row)
    await db.commit()
    try:
        await provider.preflight(settings, products)
        base = settings.BILLING_SITE_URL.rstrip('/')
        payload = {'mode': 'subscription' if product.kind == 'subscription' else 'payment',
            'line_items': [{'price': product.variant_id, 'quantity': 1}],
            'client_reference_id': row.id, 'customer_email': user.email,
            'success_url': base + '/app?checkout=' + row.id + '#credits-section',
            'cancel_url': base + '/app#credits-section', 'expires_at': int(row.expires_at.timestamp()),
            'billing_address_collection': 'required',
            'integration_identifier': 'fovea-sandbox-' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(8))}
        if product.kind == 'topup':
            payload.update({'customer_creation': 'always', 'invoice_creation': {'enabled': True}})
        if settings.STRIPE_AUTOMATIC_TAX:
            payload['automatic_tax'] = {'enabled': True}
        remote = await provider.request(settings, 'post', 'checkout/sessions', payload, key=row.id)
        service.sandbox(remote)
        if remote.get('client_reference_id') != row.id or remote.get('mode') != payload['mode']:
            raise HTTPException(502, 'Stripe Checkout response does not match')
        url = provider.safe_url(remote.get('url'))
        await lock(db)
        row = await db.get(BillingCheckout, identifier, populate_existing=True)
        row.provider_order_id = scope(settings, 'session', remote['id'])
        row.url = url
        if row.state == 'creating':
            row.state = 'open'
        await db.commit()
        return view(row)
    except Exception:
        await db.rollback()
        await lock(db)
        row = await db.get(BillingCheckout, identifier, populate_existing=True)
        if row.state == 'creating':
            row.state = 'failed'
        await db.commit()
        raise


@router.post('/webhook/stripe')
async def webhook(request: Request, stripe_signature: str | None = Header(None, alias='Stripe-Signature'), db=Depends(get_db)):
    settings, _ = configured()
    if settings.BILLING_PROVIDER != 'stripe':
        raise HTTPException(404, 'Stripe billing is not enabled')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise HTTPException(413, 'Webhook is too large')
    event = service.verify_event(bytes(body), stripe_signature, settings)
    kind = service.EVENTS.get(event.get('type'))
    if not kind:
        return {'received': True, 'ignored': True}
    obj = event.get('data', {}).get('object', {})
    identifier = obj.get('id')
    import re
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', identifier) or not str(event.get('id', '')).startswith('evt_'):
        raise HTTPException(400, 'Invalid Stripe event resource')
    eid = service.event_key(settings, event['id'])
    await lock(db)
    stored = await db.get(BillingEvent, eid, populate_existing=True)
    if stored and stored.status in ('processed', 'review'):
        return {'received': True, 'duplicate': True}
    if not stored:
        stored = BillingEvent(id=eid, event_name=event['type'], resource_id=prefix(settings) + kind + '/' + identifier,
            status='pending', attempts=0)
        db.add(stored)
    elif stored.resource_id != prefix(settings) + kind + '/' + identifier or stored.event_name != event['type']:
        raise HTTPException(409, 'Stripe event identity changed')
    await db.commit()
    applied = await service.process_inbox(db, eid, settings)
    return {'received': True, 'duplicate': not applied}


async def status(user, db, settings):
    rows = (await db.execute(select(BillingSubscription).where(BillingSubscription.user_id == user.id,
        BillingSubscription.id.startswith(prefix(settings))).order_by(BillingSubscription.provider_updated_at.desc()))).scalars()
    return {'test_mode': True, 'subscriptions': [{'id': s.id, 'status': s.status,
        'renews_at': s.renews_at, 'ends_at': s.ends_at} for s in rows]}


async def orders(user, db, settings, page, page_size):
    criteria = (BillingPayment.user_id == user.id, BillingPayment.id.startswith(prefix(settings)))
    total = (await db.execute(select(func.count()).select_from(BillingPayment).where(*criteria))).scalar_one()
    rows = (await db.execute(select(BillingPayment).where(*criteria).order_by(BillingPayment.created_at.desc(), BillingPayment.id)
        .offset((page - 1) * page_size).limit(page_size))).scalars()
    return {'orders': [{'id': p.id, 'status': p.status, 'amount_cents': p.amount_cents, 'currency': p.currency,
        'credits': p.credits if p.granted else 0, 'credits_reversed': p.revoked,
        'refunded_cents': p.refunded_cents, 'created_at': p.created_at} for p in rows],
        'total': total, 'page': page, 'page_size': page_size}


async def checkout_status(identifier, user, db, settings):
    row = owned_checkout(await db.get(BillingCheckout, identifier), user, settings)
    rows = (await db.execute(select(BillingPayment).where(BillingPayment.checkout_id == row.id,
        BillingPayment.granted.is_(True)))).scalars().all()
    confirmed = any(p.credits > p.revoked for p in rows)
    return {'checkout_id': row.id, 'state': 'refunded' if rows and not confirmed else row.state,
        'credits_confirmed': confirmed}


async def portal(identifier, user, db, settings):
    row = await db.get(BillingSubscription, identifier)
    if not row or row.user_id != user.id or not row.id.startswith(prefix(settings)):
        raise HTTPException(404, 'Subscription not found')
    config_id = await provider.validate_portal(settings)
    remote = await provider.request(settings, 'get', 'subscriptions/' + row.provider_id)
    if service.identity(remote.get('customer')) != row.customer_id:
        raise HTTPException(422, 'Stripe subscription customer does not match')
    result = await provider.request(settings, 'post', 'billing_portal/sessions', {'customer': row.customer_id,
        'configuration': config_id, 'return_url': settings.BILLING_SITE_URL.rstrip('/') + '/app#credits-section'})
    return {'url': provider.safe_url(result.get('url'))}


async def receipt(identifier, user, db, settings):
    row = await db.get(BillingPayment, identifier)
    if not row or row.user_id != user.id or not row.id.startswith(prefix(settings)):
        raise HTTPException(404, 'Payment not found')
    data = await provider.request(settings, 'get', row.resource + '/' + row.provider_id)
    if row.resource == 'checkout/sessions':
        invoice = service.identity(data.get('invoice'))
        if not invoice:
            raise HTTPException(404, 'Invoice is not available yet')
        data = await provider.request(settings, 'get', 'invoices/' + invoice)
    if not data.get('hosted_invoice_url'):
        raise HTTPException(404, 'Invoice is not available yet')
    return {'url': provider.safe_url(data['hosted_invoice_url'], receipt=True)}


async def reconcile(user, db, settings):
    # Only server-bound Checkout IDs, never caller-supplied Stripe resources.
    rows = (await db.execute(select(BillingCheckout).where(BillingCheckout.user_id == user.id,
        BillingCheckout.store_id == store(settings), BillingCheckout.provider_order_id.is_not(None))
        .order_by(BillingCheckout.created_at.desc()).limit(20))).scalars().all()
    for row in rows:
        session_id = row.provider_order_id.rsplit(':', 1)[-1]
        eid = credits.key('stripe-reconcile', row.id, secrets.token_hex(8))
        db.add(BillingEvent(id=eid, event_name='checkout.session.completed',
            resource_id=prefix(settings) + 'checkout/sessions/' + session_id, status='pending', attempts=0))
        await db.commit()
        await service.process_inbox(db, eid, settings)
    return {'checked': len(rows), 'notice': 'Renewals and risk events require webhook delivery or operator replay.'}
