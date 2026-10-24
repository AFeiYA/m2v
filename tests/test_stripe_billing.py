"""Temporary DB and mocked Stripe transport; no API key, account or live request."""
from contextlib import nullcontext
from unittest.mock import patch
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
from sqlalchemy import select
from tests.test_saas_isolation import sandbox, headers  # noqa: F401
from src import credit_lots, credits, stripe_provider as provider, stripe_service as service
from src.billing_models import BillingCheckout, BillingEvent
from src.settings import get_settings
from src.stripe_config import API_VERSION

REAL_PROVIDER_REQUEST = provider.request

PRODUCTS = [
    {'id': 'pack', 'name': '200 credits', 'variant_id': 'price_pack', 'kind': 'topup', 'credits': 200, 'price_cents': 499},
    {'id': 'monthly', 'name': '600 per month', 'variant_id': 'price_monthly', 'kind': 'subscription', 'credits': 600, 'price_cents': 999},
    {'id': 'studio', 'name': '2500 per month', 'variant_id': 'price_studio', 'kind': 'subscription', 'credits': 2500, 'price_cents': 2499},
]


@pytest.fixture
def billing(sandbox, monkeypatch):
    settings = get_settings()
    values = {'BILLING_ENABLED': True, 'BILLING_PROVIDER': 'stripe', 'BILLING_ALLOW_TEST_TRANSACTIONS': True,
        'STRIPE_API_KEY': 'rk_test_' + 'fixture', 'STRIPE_WEBHOOK_SECRET': 'whsec_fixture',
        'STRIPE_ACCOUNT_ID': 'acct_fixture', 'STRIPE_TEST_MODE': True, 'STRIPE_AUTOMATIC_TAX': False,
        'STRIPE_PORTAL_CONFIGURATION_ID': 'bpc_fixture', 'BILLING_PRODUCTS_JSON': json.dumps(PRODUCTS)}
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    remote, calls, sessions = {}, [], {}
    remote['billing_portal/configurations/bpc_fixture'] = {'active': True, 'features': {
        'subscription_update': {'enabled': False}, 'subscription_cancel': {'enabled': True, 'mode': 'at_period_end'}}}
    async def request(settings, method, path, payload=None, *, key=None):
        calls.append((method, path, copy.deepcopy(payload), key))
        if path == 'account':
            return {'id': settings.STRIPE_ACCOUNT_ID}
        if path.startswith('prices/'):
            p = next(p for p in PRODUCTS if p['variant_id'] == path.split('/')[-1])
            return {'id': p['variant_id'], 'livemode': False, 'active': True, 'currency': 'usd',
                'unit_amount': p['price_cents'], 'billing_scheme': 'per_unit', 'product': {'id': 'prod_' + p['id']},
                'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'} if p['kind'] == 'subscription' else None}
        if path == 'checkout/sessions' and method == 'post':
            sid = 'cs_test_' + str(len(sessions) + 1)
            p = next(p for p in PRODUCTS if p['variant_id'] == payload['line_items'][0]['price'])
            session = {'id': sid, 'object': 'checkout.session', 'livemode': False, 'mode': payload['mode'],
                'client_reference_id': payload['client_reference_id'], 'status': 'open', 'payment_status': 'unpaid',
                'amount_subtotal': p['price_cents'], 'amount_total': p['price_cents'], 'currency': 'usd',
                'customer': 'cus_fixture', 'subscription': 'sub_fixture' if p['kind'] == 'subscription' else None,
                'payment_intent': 'pi_fixture' if p['kind'] == 'topup' else None,
                'url': 'https://checkout.stripe.com/c/pay/' + sid}
            sessions[sid] = session
            remote[path + '/' + sid] = session
            remote[path + '/' + sid + '/line_items'] = {'data': [{'quantity': 1, 'price': {'id': p['variant_id']}}], 'has_more': False}
            return copy.deepcopy(session)
        if path == 'checkout/sessions' and method == 'get':
            matching = [s for s in sessions.values() if all(s.get(k) == v for k, v in payload.items() if k != 'limit')]
            return {'data': copy.deepcopy(matching), 'has_more': False}
        if path == 'charges':
            return copy.deepcopy(remote.get(path, {'data': [{'id': 'ch_fixture', 'livemode': False, 'paid': True,
                'captured': True, 'amount_captured': 499, 'amount_refunded': 0}], 'has_more': False}))
        if path == 'invoice_payments':
            return copy.deepcopy(remote.get(path, {'data': [], 'has_more': False}))
        if path in remote:
            return copy.deepcopy(remote[path])
        raise AssertionError('Unexpected Stripe request: ' + path)
    monkeypatch.setattr(provider, 'request', request)
    sandbox.clock = datetime(2026, 10, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(credit_lots, 'now', lambda: sandbox.clock)
    sandbox.settings, sandbox.remote, sandbox.calls, sandbox.stripe_sessions = settings, remote, calls, sessions
    return sandbox


def checkout(b, product='pack', uid='alice', key='purchase-test-0001'):
    # Seed a pre-retirement checkout for legacy webhook/refund regression tests.
    with patch('src.payments.require_subscription') if product == 'pack' else nullcontext():
        r = b.client.post('/api/payments/checkout', headers=headers(uid), json={'product_id': product, 'idempotency_key': key})
    assert r.status_code == 200, r.text
    async def read():
        async with b.sessions() as db:
            return await db.get(BillingCheckout, r.json()['checkout_id'])
    return asyncio.run(read())


def send(b, name, obj, eid='evt_fixture', **changes):
    data = {'id': eid, 'type': name, 'object': 'event', 'livemode': False, 'api_version': API_VERSION,
        'data': {'object': obj}, **changes}
    payload = json.dumps(data).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(b.settings.STRIPE_WEBHOOK_SECRET.encode(), stamp.encode() + b'.' + payload, hashlib.sha256).hexdigest()
    return b.client.post('/api/payments/webhook/stripe', content=payload,
        headers={'Content-Type': 'application/json', 'Stripe-Signature': f't={stamp},v1={digest}'})


def balance(b, uid='alice'):
    async def read():
        async with b.sessions() as db:
            value = await credits.lock_balance(db, uid)
            await db.commit()
            return value
    return asyncio.run(read())


def complete(b):
    session = list(b.stripe_sessions.values())[-1]
    session.update(status='complete', payment_status='paid')
    return session


def seed_subscription(b):
    intent = checkout(b, 'monthly')
    session = complete(b)
    start = int(b.clock.timestamp())
    end = int(datetime(2026, 11, 23, tzinfo=timezone.utc).timestamp())
    sub = {'id': 'sub_fixture', 'livemode': False, 'customer': 'cus_fixture', 'status': 'active',
        'items': {'data': [{'price': {'id': 'price_monthly'}, 'quantity': 1, 'current_period_end': end}]}}
    invoice = {'id': 'in_fixture', 'livemode': False, 'customer': 'cus_fixture', 'status': 'paid',
        'parent': {'subscription_details': {'subscription': 'sub_fixture'}}, 'currency': 'usd',
        'billing_reason': 'subscription_create', 'total': 999, 'amount_paid': 999, 'subtotal': 999,
        'lines': {'data': [{'pricing': {'price_details': {'price': 'price_monthly'}}, 'quantity': 1,
            'amount': 999, 'period': {'start': start, 'end': end},
            'parent': {'subscription_item_details': {'proration': False}}}]}}
    b.remote['subscriptions/sub_fixture'] = sub
    b.remote['invoices/in_fixture'] = invoice
    b.remote['charges'] = {'data': [{'id': 'ch_fixture', 'livemode': False, 'paid': True,
        'captured': True, 'amount_captured': 999, 'amount_refunded': 0}], 'has_more': False}
    b.remote['invoice_payments'] = {'data': [{'invoice': 'in_fixture', 'payment': {'payment_intent': 'pi_fixture'}}], 'has_more': False}
    return intent, session, sub, invoice


def test_checkout_contract_and_owner_isolation(billing):
    intent = checkout(billing)
    assert checkout(billing).id == intent.id
    assert balance(billing) == 5
    posts = [p for method, path, p, key in billing.calls if method == 'post' and path == 'checkout/sessions']
    assert len(posts) == 1
    assert posts[0]['invoice_creation'] == {'enabled': True}
    assert 'payment_method_types' not in posts[0] and 'automatic_tax' not in posts[0]
    assert posts[0]['line_items'] == [{'price': 'price_pack', 'quantity': 1}]
    assert billing.client.get('/api/payments/checkout/' + intent.id, headers=headers('bob')).status_code == 404
    catalog = billing.client.get('/api/payments/packages', headers=headers()).json()
    assert catalog['test_mode'] and catalog['provider'] == 'stripe'
    assert all('variant_id' not in p for p in catalog['products'])
    assert billing.client.get('/api/payments/packages').status_code == 401


def test_topup_duplicate_deliveries_and_event_ids_grant_once(billing):
    checkout(billing)
    data = complete(billing)
    def attempt(_):
        return send(billing, 'checkout.session.completed', data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(r.status_code == 200 for r in pool.map(attempt, range(2)))
    assert send(billing, 'checkout.session.async_payment_succeeded', data, 'evt_other').status_code == 200
    assert balance(billing) == 205 and balance(billing, 'bob') == 5
    assert len(billing.client.get('/api/payments/orders', headers=headers()).json()['orders']) == 1


def test_unpaid_return_cannot_grant_and_async_success_can(billing):
    intent = checkout(billing)
    session = list(billing.stripe_sessions.values())[-1]
    session['status'] = 'complete'
    assert send(billing, 'checkout.session.completed', session).status_code == 200
    assert balance(billing) == 5
    assert not billing.client.get('/api/payments/checkout/' + intent.id, headers=headers()).json()['credits_confirmed']
    session['payment_status'] = 'paid'
    assert send(billing, 'checkout.session.async_payment_succeeded', session, 'evt_async').status_code == 200
    assert balance(billing) == 205


def test_invalid_signatures_live_events_and_wrong_api_version_rejected(billing):
    checkout(billing)
    data = complete(billing)
    assert billing.client.post('/api/payments/webhook/stripe', content=b'{}').status_code == 401
    assert send(billing, 'checkout.session.completed', data, livemode=True).status_code == 422
    assert send(billing, 'checkout.session.completed', data, account='acct_other').status_code == 422
    assert send(billing, 'checkout.session.completed', data, api_version='old').status_code == 422
    assert balance(billing) == 5


def test_tampered_remote_price_and_client_metadata_cannot_grant(billing):
    checkout(billing)
    data = complete(billing)
    data['metadata'] = {'user_id': 'bob', 'credits': '99999'}
    data['amount_subtotal'] = 1
    assert send(billing, 'checkout.session.completed', data).status_code == 422
    assert balance(billing) == 5
    data['amount_subtotal'] = 499
    assert send(billing, 'checkout.session.completed', data).status_code == 200
    assert balance(billing) == 205 and balance(billing, 'bob') == 5


def test_subscription_first_invoice_only_renewal_and_cancellation(billing):
    _, session, sub, invoice = seed_subscription(billing)
    assert send(billing, 'checkout.session.completed', session).status_code == 200
    assert balance(billing) == 5
    assert send(billing, 'invoice.paid', invoice, 'evt_invoice').status_code == 200
    assert send(billing, 'invoice.paid', invoice, 'evt_repeat').status_code == 200
    assert balance(billing) == 605
    billing.clock = datetime(2026, 11, 23, tzinfo=timezone.utc)
    invoice2 = copy.deepcopy(invoice)
    invoice2.update(id='in_renewal', billing_reason='subscription_cycle')
    invoice2['lines']['data'][0]['period'] = {'start': int(billing.clock.timestamp()),
        'end': int(datetime(2026, 12, 23, tzinfo=timezone.utc).timestamp())}
    billing.remote['invoices/in_renewal'] = invoice2
    sub['items']['data'][0]['current_period_end'] = invoice2['lines']['data'][0]['period']['end']
    assert send(billing, 'invoice.paid', invoice2, 'evt_renewal').status_code == 200
    assert balance(billing) == 605  # Previous monthly lot expired.
    sub['cancel_at_period_end'] = True
    assert send(billing, 'customer.subscription.updated', sub, 'evt_cancel').status_code == 200
    assert balance(billing) == 605  # Cancellation is not a refund.


def test_invoice_arrives_before_session_event_and_failed_invoice_does_not_grant(billing):
    _, _, _, invoice = seed_subscription(billing)
    invoice.update(status='open', amount_paid=0)
    assert send(billing, 'invoice.payment_failed', invoice).status_code == 200
    assert balance(billing) == 5
    invoice.update(status='paid', amount_paid=999)
    assert send(billing, 'invoice.paid', invoice, 'evt_paid').status_code == 200
    assert balance(billing) == 605


def test_proration_invoice_is_not_an_extra_month(billing):
    _, _, _, invoice = seed_subscription(billing)
    invoice['billing_reason'] = 'subscription_update'
    assert send(billing, 'invoice.paid', invoice).status_code == 200
    assert balance(billing) == 5


def test_partial_and_full_refunds_are_monotonic(billing):
    checkout(billing)
    session = complete(billing)
    assert send(billing, 'checkout.session.completed', session).status_code == 200
    charge = billing.remote['charges'] = {'data': [{'id': 'ch_fixture', 'livemode': False, 'paid': True,
        'captured': True, 'amount_captured': 499, 'amount_refunded': 250, 'payment_intent': 'pi_fixture'}], 'has_more': False}
    billing.remote['charges/ch_fixture'] = charge['data'][0]
    assert send(billing, 'charge.refunded', charge['data'][0], 'evt_partial').status_code == 200
    assert balance(billing) == 104
    charge['data'][0]['amount_refunded'] = 499
    assert send(billing, 'charge.refunded', charge['data'][0], 'evt_full').status_code == 200
    assert balance(billing) == 5
    assert send(billing, 'checkout.session.completed', session, 'evt_old').status_code == 200
    assert balance(billing) == 5


def test_invoice_receipts_and_portal_require_owner(billing):
    _, session, sub, invoice = seed_subscription(billing)
    invoice['hosted_invoice_url'] = 'https://invoice.stripe.com/i/test'
    assert send(billing, 'invoice.paid', invoice).status_code == 200
    pid = billing.client.get('/api/payments/orders', headers=headers()).json()['orders'][0]['id']
    assert billing.client.post('/api/payments/receipt/' + pid, headers=headers('bob')).status_code == 404
    assert billing.client.post('/api/payments/receipt/' + pid, headers=headers()).json()['url'] == invoice['hosted_invoice_url']
    sid = billing.client.get('/api/payments/status', headers=headers()).json()['subscriptions'][0]['id']
    billing.remote['billing_portal/configurations/bpc_fixture'] = {'active': True, 'features': {
        'subscription_update': {'enabled': False}, 'subscription_cancel': {'enabled': True, 'mode': 'at_period_end'}}}
    billing.remote['billing_portal/sessions'] = {'url': 'https://billing.stripe.com/p/session/test'}
    assert billing.client.post('/api/payments/portal/' + sid, headers=headers('bob')).status_code == 404
    assert billing.client.post('/api/payments/portal/' + sid, headers=headers()).status_code == 200


def test_provider_failure_inbox_is_replayable(billing):
    checkout(billing)
    session = complete(billing)
    saved = billing.remote.pop('checkout/sessions/' + session['id'])
    with pytest.raises(AssertionError):
        send(billing, 'checkout.session.completed', session)
    billing.remote['checkout/sessions/' + session['id']] = saved
    async def replay():
        async with billing.sessions() as db:
            events = (await db.execute(select(BillingEvent))).scalars().all()
            assert len(events) == 1 and events[0].status == 'pending'
            await service.process_inbox(db, events[0].id, billing.settings)
    asyncio.run(replay())
    assert balance(billing) == 205


def test_live_credentials_and_unsafe_redirects_fail_closed(billing, monkeypatch):
    for url in ['http://checkout.stripe.com/a', 'https://checkout.stripe.com.evil.test/a', 'https://user@checkout.stripe.com/a']:
        with pytest.raises(HTTPException):
            provider.safe_url(url)
    monkeypatch.setattr(billing.settings, 'STRIPE_TEST_MODE', False)
    assert billing.client.get('/api/payments/packages', headers=headers()).status_code == 503


def test_tax_preflight_requires_registration_and_explicit_opt_in(billing, monkeypatch):
    monkeypatch.setattr(billing.settings, 'STRIPE_AUTOMATIC_TAX', True)
    request = provider.request
    async def tax_request(settings, method, path, payload=None, **kw):
        if path == 'tax/settings':
            return {'status': 'active'}
        if path == 'tax/registrations':
            return {'data': []}
        data = await request(settings, method, path, payload, **kw)
        if path.startswith('prices/'):
            data['product']['tax_code'] = 'configured-by-merchant'
            data['tax_behavior'] = 'exclusive'
        return data
    monkeypatch.setattr(provider, 'request', tax_request)
    r = billing.client.post('/api/payments/checkout', headers=headers(), json={'product_id': 'monthly', 'idempotency_key': 'tax-checkout-0001'})
    assert r.status_code == 503
    assert not any(path == 'checkout/sessions' and method == 'post' for method, path, _, _ in billing.calls)


def test_dispute_is_persisted_for_operator_review(billing):
    checkout(billing)
    session = complete(billing)
    send(billing, 'checkout.session.completed', session)
    charge = {'id': 'ch_fixture', 'livemode': False, 'payment_intent': 'pi_fixture'}
    billing.remote['charges/ch_fixture'] = charge
    dispute = {'id': 'dp_fixture', 'livemode': False, 'charge': 'ch_fixture'}
    billing.remote['disputes/dp_fixture'] = dispute
    assert send(billing, 'charge.dispute.created', dispute, 'evt_dispute').status_code == 200
    async def read():
        async with billing.sessions() as db:
            row = await db.get(BillingEvent, service.event_key(billing.settings, 'evt_dispute'))
            assert row.status == 'review' and row.last_error
    asyncio.run(read())


def test_subscription_refund_does_not_reclaim_already_expired_credits(billing):
    _, _, _, invoice = seed_subscription(billing)
    assert send(billing, 'invoice.paid', invoice).status_code == 200
    billing.clock = datetime(2026, 11, 24, tzinfo=timezone.utc)
    assert balance(billing) == 5
    charge = billing.remote['charges']['data'][0]
    charge.update(amount_refunded=999, payment_intent='pi_fixture')
    billing.remote['charges/ch_fixture'] = charge
    assert send(billing, 'charge.refunded', charge, 'evt_expiredrefund').status_code == 200
    assert balance(billing) == 5


def test_customer_portal_rejects_plan_switching(billing):
    _, _, sub, invoice = seed_subscription(billing)
    assert send(billing, 'invoice.paid', invoice).status_code == 200
    sid = billing.client.get('/api/payments/status', headers=headers()).json()['subscriptions'][0]['id']
    billing.remote['billing_portal/configurations/bpc_fixture'] = {'active': True, 'features': {
        'subscription_update': {'enabled': True}, 'subscription_cancel': {'enabled': True, 'mode': 'at_period_end'}}}
    assert billing.client.post('/api/payments/portal/' + sid, headers=headers()).status_code == 503


def test_expired_signature_is_rejected(billing):
    stamp = str(int(time.time()) - 600)
    body = b'{}'
    digest = hmac.new(billing.settings.STRIPE_WEBHOOK_SECRET.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    r = billing.client.post('/api/payments/webhook/stripe', content=body,
        headers={'Stripe-Signature': f't={stamp},v1={digest}'})
    assert r.status_code == 401


def test_real_sdk_transport_encodes_parameters_pins_version_and_redacts_errors(billing, monkeypatch):
    import httpx
    import stripe
    from urllib.parse import parse_qs
    real_http_client = stripe.HTTPXClient
    observed = []
    def handler(request):
        observed.append(request)
        if request.url.path == '/v1/checkout/sessions':
            assert request.headers['Stripe-Version'] == API_VERSION
            assert request.headers['Idempotency-Key'] == 'server-owned-intent'
            assert parse_qs(request.content.decode())['line_items[0][price]'] == ['price_pack']
            return httpx.Response(200, json={'id': 'cs_test_fixture', 'livemode': False})
        return httpx.Response(403, json={'error': {'type': 'invalid_request_error', 'message': 'private provider details'}})
    async def run():
        def factory(**kwargs):
            transport = real_http_client(**kwargs)
            transport._client_async = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return transport
        monkeypatch.setattr(stripe, 'HTTPXClient', factory)
        result = await REAL_PROVIDER_REQUEST(billing.settings, 'post', 'checkout/sessions',
            {'line_items': [{'price': 'price_pack', 'quantity': 1}], 'mode': 'payment'}, key='server-owned-intent')
        assert result['id'] == 'cs_test_fixture'
        with pytest.raises(HTTPException) as exc:
            await REAL_PROVIDER_REQUEST(billing.settings, 'get', 'account')
        assert exc.value.status_code == 502 and 'private' not in exc.value.detail
        with pytest.raises(ValueError):
            await REAL_PROVIDER_REQUEST(billing.settings, 'get', 'https://untrusted.test/')
    asyncio.run(run())
    assert len(observed) == 2


def test_subscription_only_catalog_and_retired_pack_checkout(billing, monkeypatch):
    # A legacy deployed catalogue must also stop selling top-ups immediately.
    response = billing.client.get('/api/payments/packages', headers=headers())
    assert response.status_code == 200
    assert len(response.json()['products']) == 2
    assert all(p['kind'] == 'subscription' for p in response.json()['products'])
    rejected = billing.client.post('/api/payments/checkout', headers=headers(),
        json={'product_id': 'pack', 'idempotency_key': 'retired-pack-00001'})
    assert rejected.status_code == 404
    assert not billing.calls
    values = json.loads(billing.settings.BILLING_PRODUCTS_JSON)
    monkeypatch.setattr(billing.settings, 'BILLING_PRODUCTS_JSON', json.dumps([
        p for p in values if p['kind'] == 'subscription']))
    response = billing.client.get('/api/payments/packages', headers=headers())
    assert response.status_code == 200
    assert len(response.json()['products']) == 2
    checkout(billing, product='monthly')
