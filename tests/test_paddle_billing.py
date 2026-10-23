"""Paddle sandbox contracts with temporary storage and mocked account responses."""
import asyncio
import copy
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from tests.test_saas_isolation import sandbox, headers  # noqa: F401
from src import credits, credit_lots, paddle_provider as provider, paddle_service as service, paddle_payments
from src.billing_models import BillingCheckout, BillingEvent
from src.settings import get_settings


def ident(prefix, number):
    return prefix + '_' + str(number).zfill(26)


PRODUCTS = [
    {'id': 'pack', 'name': '200 credits', 'variant_id': ident('pri', 1), 'kind': 'topup', 'credits': 200, 'price_cents': 499},
    {'id': 'monthly', 'name': '600 monthly', 'variant_id': ident('pri', 2), 'kind': 'subscription', 'credits': 600, 'price_cents': 999},
    {'id': 'studio', 'name': '2500 monthly', 'variant_id': ident('pri', 3), 'kind': 'subscription', 'credits': 2500, 'price_cents': 2499},
]
REAL_REQUEST = provider.request


@pytest.fixture
def billing(sandbox, monkeypatch):
    settings = get_settings()
    for k, v in {'BILLING_ENABLED': True, 'BILLING_PROVIDER': 'paddle', 'BILLING_ALLOW_TEST_TRANSACTIONS': True,
        'PADDLE_ENVIRONMENT': 'sandbox', 'PADDLE_API_KEY': 'pdl_sdbx_apikey_fixture', 'PADDLE_CLIENT_TOKEN': 'test_fixture',
        'PADDLE_WEBHOOK_SECRET': 'pdl_ntfset_fixture', 'BILLING_PRODUCTS_JSON': json.dumps(PRODUCTS)}.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(paddle_payments, 'async_session', sandbox.sessions)
    sandbox.clock = datetime(2026, 10, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(credit_lots, 'now', lambda: sandbox.clock)
    remote, calls, transactions = {}, [], {}
    async def request(settings, method, path, payload=None):
        calls.append((method, path, copy.deepcopy(payload)))
        if path.startswith('prices/'):
            p = next(p for p in PRODUCTS if p['variant_id'] == path.split('/')[-1])
            return {'data': {'id': p['variant_id'], 'product_id': ident('pro', PRODUCTS.index(p) + 1), 'status': 'active',
                'unit_price': {'amount': str(p['price_cents']), 'currency_code': 'USD'}, 'quantity': {'minimum': 1, 'maximum': 1},
                'trial_period': None, 'unit_price_overrides': [],
                'billing_cycle': {'interval': 'month', 'frequency': 1} if p['kind'] == 'subscription' else None}}
        if path == 'settings/checkout-url':
            return {'data': {'default_url': 'https://staging.fovea.si/app'}}
        if path == 'transactions' and method == 'POST':
            p = next(p for p in PRODUCTS if p['variant_id'] == payload['items'][0]['price_id'])
            tid = ident('txn', len(transactions) + 1)
            data = {'id': tid, 'status': 'draft', 'items': [{'price': {'id': p['variant_id'],
                    'unit_price': {'amount': str(p['price_cents']), 'currency_code': 'USD'}}, 'quantity': 1}],
                'currency_code': 'USD', 'collection_mode': 'automatic', 'origin': 'api',
                'customer_id': ident('ctm', 1), 'subscription_id': None, 'custom_data': payload['custom_data'],
                'details': {'totals': {'subtotal': str(p['price_cents']), 'total': str(p['price_cents']),
                    'grand_total': str(p['price_cents']), 'currency_code': 'USD', 'discount': '0', 'credit': '0'}}, 'adjustments': []}
            remote['transactions/' + tid] = transactions[tid] = data
            return {'data': copy.deepcopy(data)}
        if path == 'transactions' and method == 'GET':
            return {'data': [copy.deepcopy(t) for t in transactions.values() if t.get('subscription_id') == payload.get('subscription_id')],
                'meta': {'pagination': {'has_more': False}}}
        if path.endswith('/portal-sessions'):
            return {'data': {'urls': {'general': {'overview': 'https://sandbox-customer-portal.paddle.com/cpl/test'}}}}
        if path not in remote:
            raise HTTPException(502, 'Simulated Paddle outage')
        return {'data': copy.deepcopy(remote[path])}
    monkeypatch.setattr(provider, 'request', request)
    sandbox.settings, sandbox.remote, sandbox.calls, sandbox.transactions = settings, remote, calls, transactions
    return sandbox


def checkout(b, product='pack', uid='alice', key='paddle-purchase-0001'):
    r = b.client.post('/api/payments/checkout', headers=headers(uid), json={'product_id': product, 'idempotency_key': key})
    assert r.status_code == 200, r.text
    async def read():
        async with b.sessions() as db:
            return await db.get(BillingCheckout, r.json()['checkout_id'])
    return asyncio.run(read()), r.json()


def balance(b, uid='alice'):
    async def read():
        async with b.sessions() as db:
            result = await credits.lock_balance(db, uid)
            await db.commit()
            return result
    return asyncio.run(read())


def send(b, name, obj, number=1, stamp=None, signature=True):
    raw = json.dumps({'event_id': ident('evt', number), 'event_type': name,
        'occurred_at': '2026-10-23T00:00:00Z', 'data': obj}, separators=(',', ':')).encode()
    stamp = str(stamp or int(time.time()))
    digest = hmac.new(b.settings.PADDLE_WEBHOOK_SECRET.encode(), stamp.encode() + b':' + raw, hashlib.sha256).hexdigest()
    return b.client.post('/api/payments/webhook/paddle', content=raw,
        headers={'Content-Type': 'application/json', **({'Paddle-Signature': 'ts=' + stamp + ';h1=' + digest} if signature else {})})


def completed(b):
    data = list(b.transactions.values())[-1]
    data['status'] = 'completed'
    return data


def monthly(b):
    intent, view = checkout(b, 'monthly')
    transaction = completed(b)
    sub_id = ident('sub', 1)
    transaction.update(subscription_id=sub_id, billing_period={'starts_at': '2026-10-23T00:00:00Z', 'ends_at': '2026-11-23T00:00:00Z'})
    sub = {'id': sub_id, 'customer_id': ident('ctm', 1), 'items': copy.deepcopy(transaction['items']),
        'currency_code': 'USD', 'status': 'active', 'updated_at': '2026-10-23T00:00:01Z',
        'next_billed_at': '2026-11-23T00:00:00Z', 'scheduled_change': None, 'canceled_at': None}
    b.remote['subscriptions/' + sub_id] = sub
    return intent, transaction, sub


def test_checkout_uses_backend_price_and_opens_overlay_without_grant(billing):
    intent, view = checkout(billing)
    assert checkout(billing)[0].id == intent.id
    assert view['provider'] == 'paddle' and view['environment'] == 'sandbox'
    assert view['transaction_id'] == ident('txn', 1) and view['client_token'].startswith('test_')
    assert 'PADDLE_API_KEY' not in json.dumps(view) and 'custom_data' not in view
    assert len([c for c in billing.calls if c[:2] == ('POST', 'transactions')]) == 1
    assert balance(billing) == 5
    assert billing.client.get('/api/payments/checkout/' + intent.id, headers=headers('bob')).status_code == 404
    assert billing.client.get('/api/payments/packages').status_code == 401
    assert billing.client.get('/api/payments/packages', headers=headers()).json()['test_mode']
    forged = billing.client.post('/api/payments/checkout', headers=headers(), json={
        'product_id': 'pack', 'idempotency_key': 'paddle-other-0001', 'credits': 99999})
    assert forged.status_code == 422


def test_duplicate_and_parallel_events_grant_exactly_once(billing):
    checkout(billing)
    data = completed(billing)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(billing, 'transaction.completed', data), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert send(billing, 'transaction.completed', data, 2).status_code == 200
    assert balance(billing) == 205 and balance(billing, 'bob') == 5
    assert len(billing.client.get('/api/payments/orders', headers=headers()).json()['orders']) == 1


def test_paid_but_not_completed_and_failed_transactions_do_not_grant(billing):
    checkout(billing)
    data = completed(billing)
    data['status'] = 'paid'
    assert send(billing, 'transaction.completed', data).status_code == 200
    assert balance(billing) == 5
    data['status'] = 'past_due'
    assert send(billing, 'transaction.payment_failed', data, 2).status_code == 200
    assert balance(billing) == 5
    data['status'] = 'completed'
    assert send(billing, 'transaction.completed', data, 3).status_code == 200
    assert balance(billing) == 205


def test_signatures_body_and_replay_tolerance(billing):
    checkout(billing)
    data = completed(billing)
    assert send(billing, 'transaction.completed', data, signature=False).status_code == 401
    assert send(billing, 'transaction.completed', data, stamp=int(time.time()) - 30).status_code == 401
    assert billing.client.post('/api/payments/webhook/paddle', content=b'bad').status_code == 401
    assert balance(billing) == 5


def test_server_binding_ignores_forged_user_metadata_and_rejects_changed_price(billing):
    checkout(billing)
    data = completed(billing)
    data['custom_data'] = {'user_id': 'bob', 'credits': 999999}
    assert send(billing, 'transaction.completed', data).status_code == 200
    assert balance(billing) == 205 and balance(billing, 'bob') == 5
    data['items'][0]['quantity'] = 10
    assert send(billing, 'transaction.completed', data, 2).status_code == 200  # Durably queued, not fulfilled.
    assert balance(billing) == 205
    async def read():
        async with billing.sessions() as db:
            assert (await db.get(BillingEvent, service.event_key(ident('evt', 2)))).status == 'pending'
    asyncio.run(read())


def test_subscription_creation_does_not_double_grant_and_renewal_expires_previous_lot(billing):
    _, transaction, sub = monthly(billing)
    assert send(billing, 'subscription.created', sub).status_code == 200
    assert balance(billing) == 5
    assert send(billing, 'transaction.completed', transaction, 2).status_code == 200
    assert balance(billing) == 605
    assert send(billing, 'transaction.completed', transaction, 3).status_code == 200
    assert balance(billing) == 605
    renewal = copy.deepcopy(transaction)
    renewal.update(id=ident('txn', 2), origin='subscription_recurring', billing_period={
        'starts_at': '2026-11-23T00:00:00Z', 'ends_at': '2026-12-23T00:00:00Z'})
    billing.clock = datetime(2026, 11, 23, tzinfo=timezone.utc)
    billing.remote['transactions/' + renewal['id']] = billing.transactions[renewal['id']] = renewal
    sub.update(updated_at='2026-11-23T00:00:01Z', next_billed_at='2026-12-23T00:00:00Z')
    assert send(billing, 'transaction.completed', renewal, 4).status_code == 200
    assert balance(billing) == 605


def test_transaction_before_subscription_event_and_out_of_order_status(billing):
    _, transaction, sub = monthly(billing)
    assert send(billing, 'transaction.completed', transaction).status_code == 200
    sub.update(status='canceled', updated_at='2026-10-24T00:00:00Z', canceled_at='2026-11-23T00:00:00Z')
    assert send(billing, 'subscription.canceled', sub, 2).status_code == 200
    sub.update(status='active', updated_at='2026-10-23T00:00:00Z', canceled_at=None)
    assert send(billing, 'subscription.updated', sub, 3).status_code == 200
    rows = billing.client.get('/api/payments/status', headers=headers()).json()['subscriptions']
    assert rows[0]['status'] == 'canceled' and rows[0]['ends_at']
    assert balance(billing) == 605


def test_proration_and_payment_method_change_do_not_grant_extra_month(billing):
    _, transaction, _ = monthly(billing)
    transaction['origin'] = 'subscription_update'
    assert send(billing, 'transaction.completed', transaction).status_code == 200
    assert balance(billing) == 5


def refund(b, transaction, value, status='approved'):
    adjustment = {'id': ident('adj', 1), 'transaction_id': transaction['id'], 'action': 'refund',
        'status': status, 'currency_code': 'USD', 'totals': {'total': str(value)}}
    transaction['adjustments'] = [adjustment]
    b.remote['adjustments/' + adjustment['id']] = adjustment
    return adjustment


def test_pending_refund_then_partial_full_and_repeated_callbacks(billing):
    checkout(billing)
    data = completed(billing)
    send(billing, 'transaction.completed', data)
    adjustment = refund(billing, data, 250, 'pending_approval')
    assert send(billing, 'adjustment.created', adjustment, 2).status_code == 200
    assert balance(billing) == 205
    adjustment['status'] = 'approved'
    assert send(billing, 'adjustment.updated', adjustment, 3).status_code == 200
    assert balance(billing) == 104
    adjustment['totals']['total'] = '499'
    assert send(billing, 'adjustment.updated', adjustment, 4).status_code == 200
    assert send(billing, 'transaction.completed', data, 5).status_code == 200
    assert balance(billing) == 5


def test_expired_subscription_credits_are_not_reversed_twice(billing):
    _, transaction, _ = monthly(billing)
    send(billing, 'transaction.completed', transaction)
    billing.clock = datetime(2026, 11, 24, tzinfo=timezone.utc)
    assert balance(billing) == 5
    adjustment = refund(billing, transaction, 999)
    send(billing, 'adjustment.updated', adjustment, 2)
    assert balance(billing) == 5


def test_portal_and_receipt_require_owner_and_never_persist_url(billing):
    _, transaction, _ = monthly(billing)
    send(billing, 'transaction.completed', transaction)
    sid = billing.client.get('/api/payments/status', headers=headers()).json()['subscriptions'][0]['id']
    pid = billing.client.get('/api/payments/orders', headers=headers()).json()['orders'][0]['id']
    for route in ('/portal/' + sid, '/receipt/' + pid):
        assert billing.client.post('/api/payments' + route, headers=headers('bob')).status_code == 404
        assert billing.client.post('/api/payments' + route, headers=headers()).json()['url'].startswith('https://sandbox-customer-portal.paddle.com/')


def test_paddle_failure_leaves_durable_pending_event_replayable(billing):
    checkout(billing)
    data = completed(billing)
    saved = billing.remote.pop('transactions/' + data['id'])
    assert send(billing, 'transaction.completed', data).status_code == 200
    assert balance(billing) == 5
    billing.remote['transactions/' + data['id']] = saved
    async def replay():
        async with billing.sessions() as db:
            event = await db.get(BillingEvent, service.event_key(ident('evt', 1)))
            assert event.status == 'pending' and event.attempts == 1
        from src.paddle_inbox import drain
        assert await drain(billing.settings, billing.sessions) == 1
    asyncio.run(replay())
    assert balance(billing) == 205


def test_live_configuration_is_rejected(billing, monkeypatch):
    monkeypatch.setattr(billing.settings, 'PADDLE_ENVIRONMENT', 'production')
    assert billing.client.get('/api/payments/packages', headers=headers()).status_code == 503


def test_raw_body_and_multiple_signature_digests(billing):
    event = {'event_id': ident('evt', 9), 'event_type': 'subscription.created',
        'occurred_at': '2026-10-23T00:00:00Z', 'data': {'id': ident('sub', 1)}}
    raw = json.dumps(event, indent=2).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(billing.settings.PADDLE_WEBHOOK_SECRET.encode(), stamp.encode() + b':' + raw, hashlib.sha256).hexdigest()
    signature = 'ts=' + stamp + ';h1=' + '0' * 64 + ';h1=' + digest
    assert service.verify_event(raw, signature, billing.settings)['event_id'] == event['event_id']
    with pytest.raises(HTTPException):
        service.verify_event(json.dumps(event).encode(), signature, billing.settings)


def test_transport_uses_only_sandbox_and_sanitizes_errors(billing, monkeypatch):
    import httpx
    real_client = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == 'sandbox-api.paddle.com'
        assert request.headers['Paddle-Version'] == '1'
        return httpx.Response(403, json={'error': {'detail': 'private provider details'}})
    monkeypatch.setattr(provider.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    async def run():
        with pytest.raises(HTTPException) as exc:
            await REAL_REQUEST(billing.settings, 'GET', 'prices/' + PRODUCTS[0]['variant_id'])
        assert exc.value.status_code == 502 and 'private' not in exc.value.detail
        with pytest.raises(ValueError):
            await REAL_REQUEST(billing.settings, 'GET', 'https://untrusted.test')
    asyncio.run(run())
    assert len(calls) == 1


def test_webhook_external_reads_happen_only_after_response_started(billing, monkeypatch):
    checkout(billing)
    transaction = completed(billing)
    app = billing.client.app
    stack = app.middleware_stack
    started = []
    async def instrumented(scope, receive, send_message):
        async def send_checked(message):
            if message['type'] == 'http.response.start':
                started.append(True)
            await send_message(message)
        await stack(scope, receive, send_checked)
    monkeypatch.setattr(app, 'middleware_stack', instrumented)
    original = provider.request
    async def checked(*args, **kw):
        assert started, 'Paddle API request delayed webhook acknowledgment'
        return await original(*args, **kw)
    monkeypatch.setattr(provider, 'request', checked)
    assert send(billing, 'transaction.completed', transaction).status_code == 200
    assert balance(billing) == 205


def test_sandbox_launcher_overrides_production_database_and_storage(tmp_path):
    from scripts.run_paddle_sandbox import sandbox_environment
    env = sandbox_environment(tmp_path, {'DATABASE_URL': 'production', 'R2_ACCOUNT_ID': 'production',
        'S3_ACCESS_KEY': 'production', 'STORAGE_BACKEND': 'r2'}, {'PADDLE_ENVIRONMENT': 'production'}, 8896)
    assert env['DATABASE_URL'].startswith('sqlite+aiosqlite:///') and 'paddle-sandbox/sandbox.db' in env['DATABASE_URL']
    assert env['R2_ACCOUNT_ID'] == env['S3_ACCESS_KEY'] == '' and env['STORAGE_BACKEND'] == 'local'
    assert env['PADDLE_ENVIRONMENT'] == 'sandbox' and env['HOST'] == '127.0.0.1'
