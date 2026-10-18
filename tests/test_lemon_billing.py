"""Isolated provider/DB contract tests: never use a payment account or live network."""
import asyncio
import copy
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from tests.test_saas_isolation import sandbox, headers  # noqa: F401
from src import billing_provider as provider, billing_service as service, payments
from src.billing_models import BillingCheckout, BillingPayment, BillingEvent
from src.models import User, CreditEntry
from src.settings import get_settings

REAL_PROVIDER_REQUEST = provider.request

PRODUCTS=[{'id':'pack','name':'Credit pack','variant_id':'101','kind':'topup','credits':300,'price_cents':1000},
          {'id':'monthly','name':'Creator monthly','variant_id':'102','kind':'subscription','credits':900,'price_cents':1900}]


@pytest.fixture
def billing(sandbox,monkeypatch):
    settings=get_settings()
    for k,v in {'BILLING_ENABLED':True,'BILLING_ALLOW_TEST_TRANSACTIONS':True,'LEMONSQUEEZY_API_KEY':'test-not-a-real-key',
        'LEMONSQUEEZY_WEBHOOK_SECRET':'isolated-test-signing-secret','LEMONSQUEEZY_STORE_ID':'42',
        'LEMONSQUEEZY_TEST_MODE':True,'LEMONSQUEEZY_ALLOWED_HOSTS':'demo.lemonsqueezy.com',
        'BILLING_PRODUCTS_JSON':json.dumps(PRODUCTS)}.items():
        monkeypatch.setattr(settings,k,v)
    remote={};calls=[]
    async def request(settings,method,path,payload=None):
        calls.append((method,path,payload))
        if path.startswith('stores/'):
            return {'type':'stores','id':'42','attributes':{'currency':'USD'}}
        if path.startswith('prices?'):
            subscription=path.endswith('102')
            return {'type':'prices','id':'1','attributes':{'variant_id':102 if subscription else 101,'unit_price':1900 if subscription else 1000,
                'category':'subscription' if subscription else 'one_time','scheme':'standard','usage_aggregation':None,
                'setup_fee_enabled':False,'renewal_interval_unit':'month','renewal_interval_quantity':1}}
        if path.startswith('variants/'):
            subscription=path.endswith('/102')
            return {'type':'variants','id':path.split('/')[-1],'attributes':{'price':1900 if subscription else 1000,
                'test_mode':True,'is_subscription':subscription,'interval':'month','interval_count':1,'pay_what_you_want':False}}
        if method=='POST' and path=='checkouts':
            variant=payload['data']['relationships']['variant']['data']['id']
            return {'type':'checkouts','id':'checkout-1','attributes':{'store_id':42,'variant_id':int(variant),
                'test_mode':True,'url':'https://demo.lemonsqueezy.com/checkout/custom/test'}}
        if path not in remote:
            raise AssertionError('Unexpected provider request: '+path)
        return copy.deepcopy(remote[path])
    monkeypatch.setattr(provider,'request',request)
    sandbox.remote=remote;sandbox.calls=calls;sandbox.settings=settings
    return sandbox


def checkout(billing,product='pack',uid='alice',key='purchase-test-0001'):
    response=billing.client.post('/api/payments/checkout',headers=headers(uid),json={'product_id':product,'idempotency_key':key})
    assert response.status_code==200,response.text
    data=response.json()
    async def read():
        async with billing.sessions() as db:
            return await db.get(BillingCheckout,data['checkout_id'])
    return asyncio.run(read())


def resource(kind,identifier,**attrs):
    return {'type':kind,'id':str(identifier),'attributes':{'store_id':42,'test_mode':True,
        'customer_id':7,'currency':'USD','total':1000,'refunded_amount':0,'status':'paid',**attrs}}


def custom(intent):
    return {'checkout_id':intent.id,'user_id':intent.user_id,'nonce':intent.nonce}


def send(b,event,data,metadata=None,signature=True):
    b.remote[data['type']+'/'+data['id']]=data
    payload=json.dumps({'meta':{'event_name':event,'custom_data':metadata or {}},'data':data},separators=(',',':')).encode()
    sig=hmac.new(b.settings.LEMONSQUEEZY_WEBHOOK_SECRET.encode(),payload,hashlib.sha256).hexdigest()
    return b.client.post('/api/payments/webhook/lemonsqueezy',content=payload,
        headers={'Content-Type':'application/json',**({'X-Signature':sig} if signature else {})})


def balance(b,uid='alice'):
    async def read():
        async with b.sessions() as db:
            return (await db.get(User,uid)).credits
    return asyncio.run(read())


def order(identifier=301,**kw):
    return resource('orders',identifier,first_order_item=kw.pop('first_order_item',{'variant_id':101}),**kw)


def subscription(status='active',updated='2026-10-19T12:00:00Z',**kw):
    return resource('subscriptions',501,order_id=302,variant_id=102,status=status,updated_at=updated,
        renews_at='2026-11-19T12:00:00Z',ends_at=None,
        urls={'customer_portal':'https://demo.lemonsqueezy.com/billing?signature=secret'},**kw)


def invoice(identifier=601,reason='initial',**kw):
    return resource('subscription-invoices',identifier,subscription_id=501,billing_reason=reason,**kw)


def test_checkout_uses_server_product_identity_and_idempotency(billing):
    intent=checkout(billing);again=checkout(billing)
    assert intent.id==again.id and balance(billing)==5
    posts=[p for m,path,p in billing.calls if m=='POST'];assert len(posts)==1
    attributes=posts[0]['data']['attributes']
    assert attributes['checkout_data']['custom']==custom(intent)
    assert attributes['checkout_data']['variant_quantities']==[{'variant_id':101,'quantity':1}]
    assert attributes['checkout_options']['skip_trial'] is True
    assert attributes['product_options']['enabled_variants']==[101]
    invalid=billing.client.post('/api/payments/checkout',headers=headers(),json={'product_id':'pack','idempotency_key':'client-key-123456','credits':9999})
    assert invalid.status_code==422
    assert billing.client.get('/api/payments/checkout/'+intent.id,headers=headers('bob')).status_code==404
    assert billing.client.post('/api/payments/checkout',headers=headers(),json={'product_id':'monthly','idempotency_key':'purchase-test-0001'}).status_code==409


def test_webhooks_require_signature_and_matching_environment(billing):
    intent=checkout(billing)
    assert send(billing,'order_created',order(),custom(intent),False).status_code==401
    assert send(billing,'order_created',order(store_id=9),custom(intent)).status_code==422
    assert send(billing,'order_created',order(test_mode=False),custom(intent)).status_code==422
    assert send(billing,'order_created',order(),{**custom(intent),'user_id':'bob'}).status_code==422
    assert balance(billing)==5


def test_replayed_deliveries_and_parallel_events_grant_once(billing):
    intent=checkout(billing);data=order()
    def attempt(_):
        return send(billing,'order_created',data,custom(intent))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert balance(billing)==305 and balance(billing,'bob')==5
    assert send(billing,'order_created',data,custom(intent)).status_code==200
    assert billing.client.get('/api/payments/orders',headers=headers('bob')).json()['orders']==[]
    rows=billing.client.get('/api/payments/orders',headers=headers()).json()['orders']
    assert len(rows)==1 and rows[0]['credits']==300


def test_subscription_initial_invoice_only_and_renewal_once(billing):
    intent=checkout(billing,'monthly')
    first=resource('orders',302,first_order_item={'variant_id':102})
    assert send(billing,'order_created',first,custom(intent)).status_code==200
    assert balance(billing)==5
    sub=subscription();assert send(billing,'subscription_created',sub,custom(intent)).status_code==200
    assert send(billing,'subscription_payment_success',invoice()).status_code==200
    assert balance(billing)==905
    assert send(billing,'subscription_payment_recovered',invoice()).status_code==200
    assert balance(billing)==905
    assert send(billing,'subscription_payment_success',invoice(602,'renewal')).status_code==200
    assert balance(billing)==1805
    assert send(billing,'subscription_payment_success',invoice(603,'updated')).status_code==200
    assert balance(billing)==1805
    assert send(billing,'subscription_payment_failed',invoice(604,'renewal',status='pending')).status_code==200
    assert balance(billing)==1805


def test_invoice_before_subscription_retries_instead_of_losing_credit(billing):
    intent=checkout(billing,'monthly');billing.remote['subscriptions/501']=subscription()
    assert send(billing,'subscription_payment_success',invoice()).status_code==503
    assert balance(billing)==5
    assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    assert send(billing,'subscription_payment_success',invoice()).status_code==200
    assert balance(billing)==905


def test_partial_then_full_refund_reverses_once_and_can_create_debt(billing):
    intent=checkout(billing);assert send(billing,'order_created',order(),custom(intent)).status_code==200
    async def spend():
        from src.credits import reserve,finish
        async with billing.sessions() as db:
            await reserve(db,'alice','used','alignment',300)
            await finish(db,'alice','used','alignment',True);await db.commit()
    asyncio.run(spend());assert balance(billing)==5
    partial=order(status='partial_refund',refunded_amount=500)
    assert send(billing,'order_refunded',partial,custom(intent)).status_code==200
    assert balance(billing)==-145
    assert send(billing,'order_refunded',partial,custom(intent)).status_code==200
    full=order(status='refunded',refunded_amount=1000)
    assert send(billing,'order_refunded',full,custom(intent)).status_code==200
    assert balance(billing)==-295
    # Even an old paid body cannot restore refunded credits.
    assert send(billing,'order_created',order(),custom(intent)).status_code==200
    assert balance(billing)==-295
    row=billing.client.get('/api/payments/orders',headers=headers()).json()['orders'][0]
    assert row['status']=='refunded' and row['credits_reversed']==300


def test_refund_before_paid_delivery_has_zero_net_grant(billing):
    intent=checkout(billing)
    assert send(billing,'order_refunded',order(status='refunded',refunded_amount=1000),custom(intent)).status_code==200
    assert balance(billing)==5
    assert send(billing,'order_created',order(),custom(intent)).status_code==200
    assert balance(billing)==5


def test_cancelled_subscription_preserves_credits_and_portal_is_owner_scoped(billing):
    intent=checkout(billing,'monthly');assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    assert send(billing,'subscription_payment_success',invoice()).status_code==200
    cancelled=subscription('cancelled','2026-10-20T12:00:00Z');cancelled['attributes']['ends_at']='2026-11-19T12:00:00Z'
    assert send(billing,'subscription_cancelled',cancelled,custom(intent)).status_code==200
    assert balance(billing)==905
    state=billing.client.get('/api/payments/status',headers=headers()).json()['subscriptions'][0]
    sid=state['id'];assert state['status']=='cancelled' and state['ends_at']
    assert billing.client.post('/api/payments/portal/'+sid,headers=headers('bob')).status_code==404
    assert billing.client.post('/api/payments/portal/'+sid,headers=headers()).status_code==200
    assert billing.client.post('/api/payments/checkout',headers=headers(),json={'product_id':'monthly','idempotency_key':'another-monthly-001'}).status_code==409


def test_atomic_rollback_when_grant_fails_then_retry_succeeds(billing,monkeypatch):
    intent=checkout(billing);original=service.credits.grant
    async def fail(*a,**kw):
        await original(*a,**kw)
        raise HTTPException(503,'Temporary accounting error')
    monkeypatch.setattr(service.credits,'grant',fail)
    assert send(billing,'order_created',order(),custom(intent)).status_code==503
    assert balance(billing)==5
    monkeypatch.setattr(service.credits,'grant',original)
    assert send(billing,'order_created',order(),custom(intent)).status_code==200
    assert balance(billing)==305


def test_catalogue_and_redirect_fail_closed(billing,monkeypatch):
    monkeypatch.setattr(billing.settings,'BILLING_ENABLED',False)
    assert billing.client.get('/api/payments/packages',headers=headers()).status_code==404
    monkeypatch.setattr(billing.settings,'BILLING_ENABLED',True)
    for url in ('http://demo.lemonsqueezy.com/a','https://evil.invalid','https://demo.lemonsqueezy.com.evil.invalid','https://user@demo.lemonsqueezy.com'):
        with pytest.raises(HTTPException):provider.safe_url(url,billing.settings)
    monkeypatch.setattr(billing.settings,'BILLING_PRODUCTS_JSON','[{"credits":-1}]')
    assert billing.client.get('/api/payments/packages',headers=headers()).status_code==503
    assert billing.client.get('/api/payments/orders').status_code==401


def test_persisted_inbox_recovers_after_provider_failure_and_subscription_reordering(billing,monkeypatch):
    intent=checkout(billing,'monthly');billing.remote['subscriptions/501']=subscription()
    assert send(billing,'subscription_payment_success',invoice()).status_code==503
    async def pending_ids():
        async with billing.sessions() as db:
            return (await db.execute(select(BillingEvent.id).where(BillingEvent.status=='pending'))).scalars().all()
    ids=asyncio.run(pending_ids());assert len(ids)==1
    assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    async def replay():
        async with billing.sessions() as db:
            assert await service.process_inbox(db,ids[0],billing.settings) is True
        async with billing.sessions() as db:
            assert await service.process_inbox(db,ids[0],billing.settings) is False
    asyncio.run(replay());assert balance(billing)==905
    async def inspect():
        async with billing.sessions() as db:
            row=await db.get(BillingEvent,ids[0])
            assert row.status=='processed' and row.attempts==2 and row.last_error is None
    asyncio.run(inspect())


def test_provider_outage_is_retryable_and_checkout_failure_does_not_charge(billing,monkeypatch):
    original=provider.request
    async def down(*args,**kw):
        raise HTTPException(502,'Provider unavailable')
    monkeypatch.setattr(provider,'request',down)
    res=billing.client.post('/api/payments/checkout',headers=headers(),json={'product_id':'pack','idempotency_key':'outage-attempt-0001'})
    assert res.status_code==502 and balance(billing)==5
    monkeypatch.setattr(provider,'request',original)
    intent=checkout(billing,key='after-outage-00001')
    data=order();billing.remote['orders/301']=data
    monkeypatch.setattr(provider,'request',down)
    assert send(billing,'order_created',data,custom(intent)).status_code==502
    assert balance(billing)==5
    monkeypatch.setattr(provider,'request',original)
    assert send(billing,'order_created',data,custom(intent)).status_code==200
    assert balance(billing)==305


def test_receipts_are_fresh_owner_scoped_and_redirects_are_checked(billing):
    intent=checkout(billing);data=order(urls={'receipt':'https://demo.lemonsqueezy.com/receipt/signed'})
    assert send(billing,'order_created',data,custom(intent)).status_code==200
    payment=billing.client.get('/api/payments/orders',headers=headers()).json()['orders'][0]['id']
    assert billing.client.post('/api/payments/receipt/'+payment,headers=headers('bob')).status_code==404
    assert billing.client.post('/api/payments/receipt/'+payment,headers=headers()).status_code==200
    billing.remote['orders/301']['attributes']['urls']['receipt']='https://evil.invalid/path'
    assert billing.client.post('/api/payments/receipt/'+payment,headers=headers()).status_code==502


def test_one_checkout_cannot_bind_a_second_order_or_wrong_variant(billing):
    intent=checkout(billing)
    assert send(billing,'order_created',order(first_order_item={'variant_id':102}),custom(intent)).status_code==422
    assert send(billing,'order_created',order(),custom(intent)).status_code==200
    assert send(billing,'order_created',order(399),custom(intent)).status_code==409
    assert balance(billing)==305


def test_zero_total_and_wrong_currency_never_grant_paid_credits(billing):
    intent=checkout(billing)
    assert send(billing,'order_created',order(currency='EUR'),custom(intent)).status_code==422
    assert balance(billing)==5
    assert send(billing,'order_created',order(total=0),custom(intent)).status_code==200
    assert balance(billing)==5


def test_pending_invoices_never_revive_an_expired_subscription(billing):
    intent=checkout(billing,'monthly')
    assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    expired=subscription('expired','2026-11-20T12:00:00Z');expired['attributes']['ends_at']='2026-11-19T12:00:00Z'
    assert send(billing,'subscription_expired',expired,custom(intent)).status_code==200
    # Deliver older subscription data; local status must not regress.
    assert send(billing,'subscription_updated',subscription(),custom(intent)).status_code==200
    row=billing.client.get('/api/payments/status',headers=headers()).json()['subscriptions'][0]
    assert row['status']=='expired' and balance(billing)==5


def test_test_transactions_require_explicit_staging_acknowledgment(billing,monkeypatch):
    monkeypatch.setattr(billing.settings,'BILLING_ALLOW_TEST_TRANSACTIONS',False)
    assert billing.client.get('/api/payments/packages',headers=headers()).status_code==503


def test_provider_transport_prices_api_and_error_redaction(billing,monkeypatch):
    import httpx
    original=httpx.AsyncClient
    captured=[]
    def handler(request):
        captured.append(request)
        assert request.headers['authorization']=='Bearer test-not-a-real-key'
        assert request.url.host=='api.lemonsqueezy.com'
        assert request.url.params['filter[variant_id]']=='101'
        return httpx.Response(200,json={'data':[{'type':'prices','id':'newest','attributes':{'unit_price':1000}}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    from types import SimpleNamespace
    settings=SimpleNamespace(LEMONSQUEEZY_API_KEY='test-not-a-real-key')
    result=asyncio.run(REAL_PROVIDER_REQUEST(settings,'GET','prices?filter[variant_id]=101'))
    assert result['id']=='newest' and len(captured)==1
    def broken(request):
        return httpx.Response(500,text='private token or customer data')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(broken),**kw))
    with pytest.raises(HTTPException) as error:
        asyncio.run(REAL_PROVIDER_REQUEST(settings,'GET','orders/301'))
    assert error.value.status_code==502 and 'private' not in error.value.detail


def test_large_webhooks_and_unimplemented_prices_fail_closed(billing,monkeypatch):
    response=billing.client.post('/api/payments/webhook/lemonsqueezy',content=b'x'*65537)
    assert response.status_code==413
    monkeypatch.setattr(billing.settings,'MOTION_EXPORT_CREDITS',10)
    assert billing.client.get('/api/payments/packages',headers=headers()).status_code==503


def test_billing_responses_are_not_cacheable(billing):
    response=billing.client.get('/api/payments/packages',headers=headers())
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store, private'


@pytest.mark.parametrize('refund_first',[False,True])
def test_subscription_initial_order_refund_does_not_require_invoice_refund_event(billing,refund_first):
    intent=checkout(billing,'monthly')
    assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    refunded=resource('orders',302,first_order_item={'variant_id':102},status='refunded',refunded_amount=1000)
    if refund_first:
        assert send(billing,'order_refunded',refunded,custom(intent)).status_code==200
    assert send(billing,'subscription_payment_success',invoice()).status_code==200
    if not refund_first:
        assert balance(billing)==905
        assert send(billing,'order_refunded',refunded,custom(intent)).status_code==200
    assert balance(billing)==5
    assert send(billing,'subscription_payment_success',invoice(602,'renewal')).status_code==200
    assert balance(billing)==905  # A refund of the initial order cannot confiscate renewals.
    assert send(billing,'subscription_payment_refunded',invoice(status='refunded',refunded_amount=1000)).status_code==200
    assert balance(billing)==905  # Both objects describe one refund, not two.
