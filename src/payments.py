"""Opt-in Lemon Squeezy hosted checkout. All grants come from verified webhooks."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from src.auth import get_current_user
from src.database import get_db
from src.models import User
from src.billing_models import BillingCheckout, BillingEvent, BillingPayment, BillingSubscription
from src.billing_config import configured
from src import billing_provider as provider, billing_service as service, credits

def no_store(response:Response):
    response.headers['Cache-Control']='no-store, private'


router=APIRouter(prefix='/api/payments',tags=['Billing'],dependencies=[Depends(no_store)])
EVENTS={
    'order_created':'orders','order_refunded':'orders',
    **{name:'subscriptions' for name in ('subscription_created','subscription_updated','subscription_cancelled',
       'subscription_resumed','subscription_expired','subscription_paused','subscription_unpaused')},
    **{name:'subscription-invoices' for name in ('subscription_payment_success','subscription_payment_recovered',
       'subscription_payment_failed','subscription_payment_refunded')},
}


class CheckoutRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    product_id: str = Field(min_length=1,max_length=64)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,128}$')


def now():
    return datetime.now(timezone.utc)


def intent_view(row,settings):
    if row.state=='creating':
        raise HTTPException(409,'Checkout is still being created. Refresh billing before retrying.')
    if row.state=='failed':
        raise HTTPException(409,'Checkout creation was interrupted. Check your orders, then start a new checkout.')
    if row.state=='paid':
        return {'checkout_id':row.id,'state':'paid','url':None}
    if service.utc(row.expires_at)<=now():
        raise HTTPException(410,'Checkout expired. Start a new checkout.')
    return {'checkout_id':row.id,'state':row.state,'url':provider.safe_url(row.url,settings)}


@router.get('/packages')
async def packages(user:User=Depends(get_current_user)):
    settings,products=configured()
    return {'test_mode':settings.LEMONSQUEEZY_TEST_MODE,'products':[p.model_dump(exclude={'variant_id'}) for p in products.values()],
            'credit_policy':'Credits are added after confirmed payment and carry over. Monthly credits are added, not a balance reset. Refunds reverse the corresponding credits; spent refunded credits become a balance to repay.',
            'subscription_policy':'Monthly automatic renewal until cancelled in the billing portal. No unlimited rendering or extra storage is included.'}


@router.post('/checkout')
async def checkout(req:CheckoutRequest,user:User=Depends(get_current_user),db=Depends(get_db)):
    settings,products=configured(); product=products.get(req.product_id)
    if not product:
        raise HTTPException(400,'Unknown billing product')
    identifier=credits.key('lemon-checkout',user.id,req.idempotency_key)
    await service.lock(db)
    existing=await db.get(BillingCheckout,identifier,populate_existing=True)
    if existing:
        if existing.product_id!=req.product_id or existing.test_mode is not settings.LEMONSQUEEZY_TEST_MODE or existing.store_id!=settings.LEMONSQUEEZY_STORE_ID:
            raise HTTPException(409,'Checkout key was used for a different product or environment')
        return intent_view(existing,settings)
    if product.kind=='subscription':
        subscriptions=(await db.execute(select(BillingSubscription).where(BillingSubscription.user_id==user.id))).scalars()
        for sub in subscriptions:
            if sub.id.startswith(service.scope(settings,'sub','')) and sub.status!='expired' and (not sub.ends_at or service.utc(sub.ends_at)>now()):
                raise HTTPException(409,'You already have a subscription. Manage it in the billing portal.')
    pending=(await db.execute(select(BillingCheckout).where(BillingCheckout.user_id==user.id,
        BillingCheckout.product_id==product.id,BillingCheckout.store_id==settings.LEMONSQUEEZY_STORE_ID,BillingCheckout.test_mode==settings.LEMONSQUEEZY_TEST_MODE,
        BillingCheckout.state.in_(['creating','open']),BillingCheckout.expires_at>now()).order_by(BillingCheckout.created_at.desc()))).scalars().first()
    if pending:
        return intent_view(pending,settings)
    recent=(await db.execute(select(func.count()).select_from(BillingCheckout).where(
        BillingCheckout.user_id==user.id,BillingCheckout.created_at>now()-timedelta(hours=1)))).scalar_one()
    if recent>=10:
        raise HTTPException(429,'Too many checkout attempts. Try again later.')
    row=BillingCheckout(id=identifier,user_id=user.id,product_id=product.id,name=product.name,kind=product.kind,
        variant_id=product.variant_id,credits=product.credits,price_cents=product.price_cents,currency=product.currency,
        test_mode=settings.LEMONSQUEEZY_TEST_MODE,store_id=settings.LEMONSQUEEZY_STORE_ID,nonce=secrets.token_hex(24),state='creating',expires_at=now()+timedelta(minutes=30))
    db.add(row); await db.commit()  # Do not hold database locks during remote requests.
    try:
        await provider.validate_product(settings,product)
        payload={'data':{'type':'checkouts','attributes':{
            'test_mode':settings.LEMONSQUEEZY_TEST_MODE,'expires_at':row.expires_at.isoformat(),
            'product_options':{'enabled_variants':[int(product.variant_id)],
                'redirect_url':settings.BILLING_SITE_URL.rstrip('/')+'/?checkout='+row.id+'#credits-section'},
            'checkout_options':{'embed':False,'discount':False,'skip_trial':True},
            'checkout_data':{'email':user.email,'custom':{'user_id':user.id,'checkout_id':row.id,'nonce':row.nonce},
                'variant_quantities':[{'variant_id':int(product.variant_id),'quantity':1}]}},
            'relationships':{'store':{'data':{'type':'stores','id':settings.LEMONSQUEEZY_STORE_ID}},
                             'variant':{'data':{'type':'variants','id':product.variant_id}}}}}
        remote=await provider.request(settings,'POST','checkouts',payload)
        a=remote['attributes']
        if str(a.get('store_id'))!=settings.LEMONSQUEEZY_STORE_ID or str(a.get('variant_id'))!=product.variant_id or a.get('test_mode') is not settings.LEMONSQUEEZY_TEST_MODE:
            raise HTTPException(502,'Checkout environment does not match')
        url=provider.safe_url(a.get('url'),settings)
        await service.lock(db)
        row=await db.get(BillingCheckout,identifier,populate_existing=True)
        row.url=url
        if row.state=='creating':
            row.state='open'
        await db.commit()
        return intent_view(row,settings)
    except Exception:
        await db.rollback()
        await service.lock(db)
        row=await db.get(BillingCheckout,identifier,populate_existing=True)
        if row.state=='creating':
            row.state='failed'
        await db.commit()
        raise


@router.post('/webhook/lemonsqueezy')
async def webhook(request:Request,x_signature:str|None=Header(None,alias='X-Signature'),db=Depends(get_db)):
    settings,_=configured()
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>65536:
            raise HTTPException(413,'Webhook is too large')
    raw=bytes(body)
    expected=hmac.new(settings.LEMONSQUEEZY_WEBHOOK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
    if not x_signature or not re.fullmatch(r'[a-f0-9]{64}',x_signature) or not hmac.compare_digest(expected,x_signature):
        raise HTTPException(401,'Invalid webhook signature')
    try:
        event=json.loads(raw); meta=event['meta']; data=event['data']
        name=meta['event_name']; kind=data['type']; identifier=str(data['id'])
        custom=meta.get('custom_data') or {}
        if not isinstance(custom,dict) or not isinstance(name,str) or not re.fullmatch(r'\d{1,32}',identifier):
            raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise HTTPException(400,'Invalid webhook body') from None
    if name not in EVENTS:
        return {'received':True,'ignored':True}
    if EVENTS[name]!=kind:
        raise HTTPException(422,'Webhook resource type does not match event')
    service.validate_resource(data,settings,kind,identifier)
    # Commit a minimal inbox before any provider call. Failed processing is replayable
    # even after the provider exhausts its automatic delivery attempts.
    await service.lock(db)
    event_id=hashlib.sha256(raw).hexdigest()
    stored=await db.get(BillingEvent,event_id,populate_existing=True)
    if stored and stored.status=='processed':
        return {'received':True,'duplicate':True}
    if not stored:
        intent=None
        if custom:
            intent=await db.get(BillingCheckout,str(custom.get('checkout_id','')))
            if not intent or intent.user_id!=custom.get('user_id') or not hmac.compare_digest(intent.nonce,str(custom.get('nonce',''))):
                raise HTTPException(422,'Checkout ownership could not be verified')
        stored=BillingEvent(id=event_id,event_name=name,resource_id=service.scope(settings,kind,identifier),
            routing_checkout_id=intent.id if intent else None,status='pending',attempts=0)
        db.add(stored)
    await db.commit()
    applied=await service.process_inbox(db,event_id,settings)
    return {'received':True,'duplicate':not applied}


@router.get('/status')
async def status(user:User=Depends(get_current_user),db=Depends(get_db)):
    settings,_=configured()
    mode=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
    subs=(await db.execute(select(BillingSubscription).where(BillingSubscription.user_id==user.id,
        BillingSubscription.id.startswith(mode)).order_by(BillingSubscription.provider_updated_at.desc()))).scalars()
    return {'test_mode':settings.LEMONSQUEEZY_TEST_MODE,'subscriptions':[{
        'id':s.id,'status':s.status,'renews_at':s.renews_at,'ends_at':s.ends_at} for s in subs]}


@router.get('/orders')
async def orders(user:User=Depends(get_current_user),db=Depends(get_db),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50)):
    settings,_=configured(); mode=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
    criteria=(BillingPayment.user_id==user.id,BillingPayment.id.startswith(mode))
    total=(await db.execute(select(func.count()).select_from(BillingPayment).where(*criteria))).scalar_one()
    rows=(await db.execute(select(BillingPayment).where(*criteria).order_by(BillingPayment.created_at.desc(),BillingPayment.id).offset((page-1)*page_size).limit(page_size))).scalars()
    return {'orders':[{'id':p.id,'status':p.status,'amount_cents':p.amount_cents,'currency':p.currency,
        'credits':p.credits if p.granted else 0,'credits_reversed':p.revoked,'refunded_cents':p.refunded_cents,
        'created_at':p.created_at} for p in rows],'total':total,'page':page,'page_size':page_size}


@router.get('/checkout/{checkout_id}')
async def checkout_status(checkout_id:str,user:User=Depends(get_current_user),db=Depends(get_db)):
    settings,_=configured()
    row=await db.get(BillingCheckout,checkout_id)
    if not row or row.user_id!=user.id or row.test_mode is not settings.LEMONSQUEEZY_TEST_MODE or row.store_id!=settings.LEMONSQUEEZY_STORE_ID:
        raise HTTPException(404,'Checkout not found')
    paid=(await db.execute(select(BillingPayment).where(BillingPayment.checkout_id==row.id,BillingPayment.granted.is_(True)))).scalars().all()
    confirmed=any(p.credits>p.revoked for p in paid)
    state='refunded' if paid and not confirmed else row.state
    return {'checkout_id':row.id,'state':state,'credits_confirmed':confirmed}


@router.post('/portal/{subscription_id}')
async def portal(subscription_id:str,user:User=Depends(get_current_user),db=Depends(get_db)):
    settings,_=configured(); row=await db.get(BillingSubscription,subscription_id)
    if not row or row.user_id!=user.id or not row.id.startswith(service.scope(settings,'sub','')):
        raise HTTPException(404,'Subscription not found')
    remote=await provider.request(settings,'GET','subscriptions/'+row.provider_id)
    a=service.validate_resource(remote,settings,'subscriptions',row.provider_id)
    if str(a.get('customer_id'))!=row.customer_id:
        raise HTTPException(422,'Subscription customer does not match')
    return {'url':provider.safe_url((a.get('urls') or {}).get('customer_portal'),settings)}


@router.post('/reconcile')
async def reconcile(user:User=Depends(get_current_user),db=Depends(get_db)):
    """Owner-triggered recovery of known records only; unknown purchases need webhook replay."""
    settings,_=configured(); mode=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
    rows=(await db.execute(select(BillingPayment).where(BillingPayment.user_id==user.id,
        BillingPayment.id.startswith(mode)).order_by(BillingPayment.created_at.desc()).limit(20))).scalars().all()
    for row in rows:
        data=await provider.request(settings,'GET',row.resource+'/'+row.provider_id)
        await service.lock(db)
        intent=await db.get(BillingCheckout,row.checkout_id)
        sub=await db.get(BillingSubscription,row.subscription_id) if row.subscription_id else None
        if sub:
            remote=await provider.request(settings,'GET','subscriptions/'+sub.provider_id)
            await service.sync_subscription(db,remote,settings)
        await service.sync_payment(db,data,intent,settings,sub)
        await db.commit()
    return {'checked':len(rows),'notice':'Missing new purchases require webhook delivery or replay from the merchant dashboard.'}


@router.post('/receipt/{payment_id}')
async def receipt(payment_id:str,user:User=Depends(get_current_user),db=Depends(get_db)):
    settings,_=configured(); row=await db.get(BillingPayment,payment_id)
    if not row or row.user_id!=user.id or not row.id.startswith(f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'):
        raise HTTPException(404,'Payment not found')
    remote=await provider.request(settings,'GET',row.resource+'/'+row.provider_id)
    a=service.validate_resource(remote,settings,row.resource,row.provider_id)
    key='invoice_url' if row.resource=='subscription-invoices' else 'receipt'
    url=(a.get('urls') or {}).get(key)
    if not url:
        raise HTTPException(404,'Receipt is not available yet')
    return {'url':provider.safe_url(url,settings)}
