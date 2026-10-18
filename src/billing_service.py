"""Atomic provider binding, paid-credit grants and cumulative refund reversals."""
import hmac
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from src import billing_provider as provider, credits
from src.billing_models import BillingMutex, BillingCheckout, BillingSubscription, BillingPayment, BillingEvent
from src.models import CreditEntry, User


def utc(value):
    if value is None:
        return None
    if isinstance(value,str):
        try:
            value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            raise HTTPException(422,'Invalid billing timestamp') from None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def scope(settings, resource, identifier):
    return f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:{resource}:{identifier}'


async def lock(db):
    # The lock covers binding and balance mutation in ONE transaction, across replicas.
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    await db.execute(insert(BillingMutex).values(id='global').on_conflict_do_nothing())
    await db.execute(update(BillingMutex).where(BillingMutex.id=='global').values(id='global'))


def validate_resource(data, settings, kind, identifier):
    attrs=data.get('attributes',{})
    if not isinstance(attrs,dict):
        raise HTTPException(422,'Invalid billing resource attributes')
    if data.get('type')!=kind or str(data.get('id'))!=identifier:
        raise HTTPException(422,'Billing resource does not match')
    if str(attrs.get('store_id'))!=settings.LEMONSQUEEZY_STORE_ID or attrs.get('test_mode') is not settings.LEMONSQUEEZY_TEST_MODE:
        raise HTTPException(422,'Billing store or environment does not match')
    return attrs


async def bind_checkout(db, custom, variant_id, order_id, settings):
    intent=await db.get(BillingCheckout,str(custom.get('checkout_id','')),populate_existing=True)
    if not intent or intent.user_id!=custom.get('user_id') or not hmac.compare_digest(intent.nonce,str(custom.get('nonce',''))):
        raise HTTPException(422,'Checkout ownership could not be verified')
    if intent.test_mode is not settings.LEMONSQUEEZY_TEST_MODE or intent.store_id!=settings.LEMONSQUEEZY_STORE_ID or intent.variant_id!=str(variant_id):
        raise HTTPException(422,'Checkout product does not match')
    identity=scope(settings,'order',order_id)
    if intent.provider_order_id and intent.provider_order_id!=identity:
        raise HTTPException(409,'Checkout already belongs to a different purchase')
    existing=(await db.execute(select(BillingCheckout).where(BillingCheckout.provider_order_id==identity))).scalar_one_or_none()
    if existing and existing.id!=intent.id:
        raise HTTPException(409,'Purchase is already bound')
    intent.provider_order_id=identity
    return intent


async def sync_subscription(db, data, settings, custom=None):
    identifier=str(data['id']); attrs=validate_resource(data,settings,'subscriptions',identifier)
    sid=scope(settings,'sub',identifier)
    row=await db.get(BillingSubscription,sid,populate_existing=True)
    if not row:
        if not custom:
            raise HTTPException(503,'Subscription checkout is not linked yet; retry this event')
        intent=await bind_checkout(db,custom,attrs.get('variant_id'),str(attrs.get('order_id')),settings)
        if intent.kind!='subscription':
            raise HTTPException(422,'Not a subscription checkout')
        row=BillingSubscription(id=sid,provider_id=identifier,user_id=intent.user_id,checkout_id=intent.id,
            customer_id=str(attrs['customer_id']),variant_id=str(attrs['variant_id']),
            status='unknown',provider_updated_at=datetime(1970,1,1,tzinfo=timezone.utc))
        db.add(row)
        await db.flush()
    intent=await db.get(BillingCheckout,row.checkout_id)
    if str(attrs.get('order_id'))!=intent.provider_order_id.rsplit(':',1)[-1] or str(attrs.get('customer_id'))!=row.customer_id:
        raise HTTPException(422,'Subscription identity changed')
    # Tier changes are deliberately disabled in the provider portal for this release.
    if str(attrs.get('variant_id'))!=row.variant_id:
        raise HTTPException(409,'Subscription variant changed; billing review required')
    updated=utc(attrs.get('updated_at'))
    if updated is None:
        raise HTTPException(422,'Missing subscription update time')
    if updated>=utc(row.provider_updated_at):
        row.status=str(attrs.get('status','unknown'))[:24]
        row.renews_at=utc(attrs.get('renews_at')); row.ends_at=utc(attrs.get('ends_at'))
        row.provider_updated_at=updated
    intent.state='paid'
    await db.flush()
    return row,intent


async def reverse(db, payment, target):
    delta=target-payment.revoked
    if delta<=0 or not payment.granted:
        return
    balance=await credits.lock_balance(db,payment.user_id)
    await credits.opening(db,payment.user_id,balance)
    balance-=delta  # Spent refunded credits become debt; never silently mint a refund.
    await db.execute(update(User).where(User.id==payment.user_id).values(credits=balance))
    db.add(CreditEntry(id=credits.key(payment.id,'refund',target),user_id=payment.user_id,
        operation_id=payment.id,kind='billing',event='reversal',amount=-delta,balance_after=balance,
        description='Payment refund · credits reversed'))
    payment.revoked=target


async def sync_payment(db, data, intent, settings, subscription=None):
    kind=data['type']; identifier=str(data['id']); a=validate_resource(data,settings,kind,identifier)
    if a.get('currency')!=intent.currency:
        raise HTTPException(422,'Payment currency does not match checkout')
    total=a.get('total'); refund=a.get('refunded_amount',0)
    if type(total) is not int or total<0 or type(refund) is not int or not 0<=refund<=total:
        raise HTTPException(422,'Invalid payment totals')
    payment_id=scope(settings,'invoice' if subscription else 'order',identifier)
    row=await db.get(BillingPayment,payment_id,populate_existing=True)
    if row and row.checkout_id!=intent.id:
        raise HTTPException(409,'Payment is already owned')
    if not row:
        row=BillingPayment(id=payment_id,provider_id=identifier,resource=kind,user_id=intent.user_id,
            checkout_id=intent.id,subscription_id=subscription.id if subscription else None,
            billing_reason=a.get('billing_reason') if subscription else None,
            amount_cents=total,currency=intent.currency,credits=intent.credits,granted=False,
            revoked=0,refunded_cents=0,status='pending')
        db.add(row)
        await db.flush()
    if total!=row.amount_cents:
        raise HTTPException(409,'Payment total changed')
    # Use resource identity, not delivery/body identity, as the money idempotency key.
    paid=a.get('status') in ('paid','partial_refund','refunded')
    fully_refunded=a.get('status') in ('refunded','fraudulent') or a.get('refunded') is True
    row.refunded_cents=max(row.refunded_cents,total if fully_refunded else refund)
    if paid and total>0 and not row.granted:
        await credits.grant(db,row.user_id,row.credits,'ls:'+row.id,
            ('Monthly credits' if subscription else 'Credit pack')+' · '+intent.name)
        row.granted=True
    target=(row.credits*row.refunded_cents+total-1)//total if total else 0
    await reverse(db,row,target)
    if subscription and row.billing_reason=='initial':
        await initial_order_refund(db,row,intent)
    # Refunds are monotonic even if an old paid callback arrives afterwards.
    row.status='refunded' if fully_refunded or row.revoked==row.credits or (total and row.refunded_cents==total) else 'partial_refund' if row.refunded_cents or row.revoked else 'paid' if row.granted else str(a.get('status','pending'))[:24]
    if paid:
        intent.state='paid'
    await db.flush()
    return row


async def initial_order_refund(db,payment,intent):
    # The first subscription payment has both an Order and an Invoice. A refund
    # reported on either object reverses the same grant, never the renewal grants.
    total=intent.order_total_cents
    refunded=intent.order_refunded_cents or 0
    if not total or not refunded:
        return
    target=(payment.credits*refunded+total-1)//total
    await reverse(db,payment,target)
    if payment.revoked:
        payment.status='refunded' if payment.revoked==payment.credits else 'partial_refund'


async def apply_event(db,event_name,data,custom,settings):
    kind=data['type']; identifier=str(data['id'])
    if kind=='subscriptions':
        await sync_subscription(db,data,settings,custom)
    elif kind=='orders':
        a=validate_resource(data,settings,kind,identifier)
        item=a.get('first_order_item') or {}
        intent=await bind_checkout(db,custom,item.get('variant_id'),identifier,settings)
        if intent.kind=='topup':
            await sync_payment(db,data,intent,settings)
        else:
            total=a.get('total'); refunded=a.get('refunded_amount',0)
            if a.get('currency')!=intent.currency or type(total) is not int or total<0 or type(refunded) is not int or not 0<=refunded<=total:
                raise HTTPException(422,'Invalid subscription order refund')
            if intent.order_total_cents is not None and intent.order_total_cents!=total:
                raise HTTPException(409,'Subscription order total changed')
            intent.order_total_cents=total
            intent.order_refunded_cents=max(intent.order_refunded_cents or 0,total if a.get('refunded') or a.get('status') in ('refunded','fraudulent') else refunded)
            initial=(await db.execute(select(BillingPayment).where(BillingPayment.checkout_id==intent.id,
                BillingPayment.billing_reason=='initial'))).scalars().all()
            for payment in initial:
                await initial_order_refund(db,payment,intent)
        # Subscription order is never credited: its initial invoice is the sole grant.
    elif kind=='subscription-invoices':
        a=validate_resource(data,settings,kind,identifier)
        sub_id=str(a.get('subscription_id',''))
        remote=await provider.request(settings,'GET','subscriptions/'+sub_id)
        subscription,intent=await sync_subscription(db,remote,settings,custom or None)
        if str(a.get('customer_id'))!=subscription.customer_id:
            raise HTTPException(422,'Invoice customer does not match subscription')
        if a.get('billing_reason') in ('initial','renewal'):
            await sync_payment(db,data,intent,settings,subscription)
        # Proration/update invoices do not buy a second full monthly allocation.


async def process_inbox(db,event_id,settings):
    """Replayable minimal inbox; never persist full payloads, emails or card fields."""
    event=await db.get(BillingEvent,event_id,populate_existing=True)
    if not event:
        raise HTTPException(404,'Billing event not found')
    if event.status=='processed':
        return False
    _,store,kind,identifier=event.resource_id.split(':',3)
    if store!=settings.LEMONSQUEEZY_STORE_ID or not event.resource_id.startswith(str(int(settings.LEMONSQUEEZY_TEST_MODE))+':'):
        raise HTTPException(422,'Billing event environment does not match')
    try:
        data=await provider.request(settings,'GET',kind+'/'+identifier)
        attrs=validate_resource(data,settings,kind,identifier)
        if event.event_name in ('order_refunded','subscription_payment_refunded') and not (attrs.get('refunded') or attrs.get('refunded_amount',0)>0 or attrs.get('status')=='refunded'):
            raise HTTPException(503,'Provider refund is not visible yet; retry this event')
        await lock(db)
        event=await db.get(BillingEvent,event_id,populate_existing=True)
        if event.status=='processed':
            return False
        intent=await db.get(BillingCheckout,event.routing_checkout_id) if event.routing_checkout_id else None
        if not intent and kind=='orders':
            intent=(await db.execute(select(BillingCheckout).where(BillingCheckout.provider_order_id==scope(settings,'order',identifier)))).scalar_one_or_none()
        custom={'checkout_id':intent.id,'user_id':intent.user_id,'nonce':intent.nonce} if intent else {}
        await apply_event(db,event.event_name,data,custom,settings)
        event.status='processed';event.attempts+=1;event.last_error=None
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        await lock(db)
        event=await db.get(BillingEvent,event_id,populate_existing=True)
        if event.status!='processed':
            event.status='pending';event.attempts+=1;event.last_error='Provider synchronization failed; retry required'
        await db.commit()
        raise
