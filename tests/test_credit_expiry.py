"""Billing-period credits never roll over or erase permanent purchased credits."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import select
from tests.test_saas_isolation import sandbox, headers  # noqa: F401
from tests.test_lemon_billing import billing,checkout,send,order,subscription,invoice,custom,balance  # noqa: F401
from src import credits
from src.billing_service import period_end
from src.credit_lots import CreditLot
from src.models import CreditEntry


def buy_pack(b):
    intent=checkout(b)
    assert send(b,'order_created',order(),custom(intent)).status_code==200
    return intent


def buy_month(b,plus=False):
    intent=checkout(b,'monthly_plus' if plus else 'monthly',key='monthly-purchase-0001')
    sub=subscription()
    if plus:sub['attributes']['variant_id']=103
    assert send(b,'subscription_created',sub,custom(intent)).status_code==200
    assert send(b,'subscription_payment_success',invoice(total=1000 if plus else 500)).status_code==200
    return intent


def usage(b,amount,success=None,identifier='render'):
    async def run():
        async with b.sessions() as db:
            await credits.reserve(db,'alice',identifier,'lyric_export',amount)
            if success is not None:
                await credits.finish(db,'alice',identifier,'lyric_export',success)
            await db.commit()
    asyncio.run(run())


def release(b,identifier='render'):
    async def run():
        async with b.sessions() as db:
            result=await credits.finish(db,'alice',identifier,'lyric_export',False)
            await db.commit();return result
    return asyncio.run(run())


def history(b):
    response=b.client.get('/api/credits',headers=headers())
    assert response.status_code==200,response.text
    return response.json()


def test_legacy_catalog_only_offers_subscriptions_with_billing_period_validity(billing):
    response=billing.client.get('/api/payments/packages',headers=headers())
    products=response.json()['products']
    assert {(p['kind'],p['price_cents'],p['credits'],p['validity']) for p in products}=={
        ('subscription',500,1000,'billing_period'),('subscription',1000,2500,'billing_period')}
    buy_month(billing,plus=True)
    assert balance(billing)==2505


def test_expiry_only_removes_monthly_balance_and_is_idempotent(billing):
    buy_pack(billing);buy_month(billing)
    before=history(billing)
    assert before['available']==1505
    assert before['wallet']['subscription_available']==1000
    assert before['wallet']['permanent_available']==505
    billing.clock=datetime(2026,11,19,12,tzinfo=timezone.utc)
    after=history(billing)
    assert after['available']==505 and after['wallet']['subscription_available']==0
    assert after['wallet']['permanent_available']==505
    expired=[e for e in after['entries'] if e['event']=='expire']
    assert len(expired)==1 and expired[0]['amount']==-1000
    assert history(billing)['total']==after['total']
    assert balance(billing,'bob')==5


def test_usage_spends_monthly_credits_before_permanent_pack(billing):
    buy_pack(billing);buy_month(billing);usage(billing,200,True)
    data=history(billing)
    assert data['available']==1305
    assert data['wallet']['subscription_available']==800 and data['wallet']['permanent_available']==505
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert history(billing)['available']==505


def test_failed_job_after_expiry_returns_only_its_permanent_portion(billing):
    buy_pack(billing);buy_month(billing);usage(billing,1100)
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert release(billing) is True and release(billing) is False
    data=history(billing)
    assert data['available']==505 and data['reserved']==0
    returned=[e for e in data['entries'] if e['event']=='release']
    assert returned[0]['amount']==100
    assert sum(e['amount'] for e in data['entries'])==505


def test_failed_job_before_expiry_restores_original_wallets(billing):
    buy_pack(billing);buy_month(billing);usage(billing,1100)
    assert release(billing) is True
    data=history(billing)
    assert data['available']==1505 and data['wallet']['subscription_available']==1000
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert history(billing)['available']==505


def test_successful_renewal_resets_unused_period_without_touching_pack(billing):
    buy_pack(billing);buy_month(billing);usage(billing,200,True)
    assert send(billing,'subscription_payment_success',invoice(602,'renewal')).status_code==200
    data=history(billing)
    assert data['available']==1505  # 800 old credits expire; 1,000 new credits arrive.
    assert data['wallet']['subscription_available']==1000 and data['wallet']['permanent_available']==505
    assert send(billing,'subscription_payment_recovered',invoice(602,'renewal')).status_code==200
    assert history(billing)['available']==1505


def test_late_old_invoice_cannot_reopen_or_reset_new_period(billing):
    intent=checkout(billing,'monthly')
    assert send(billing,'subscription_created',subscription(),custom(intent)).status_code==200
    assert send(billing,'subscription_payment_success',invoice(602,'renewal')).status_code==200
    assert balance(billing)==1005
    assert send(billing,'subscription_payment_success',invoice()).status_code==200
    assert history(billing)['available']==1005
    assert history(billing)['wallet']['subscription_available']==1000


def test_permanent_pack_has_no_time_expiry(billing):
    buy_pack(billing)
    billing.clock=datetime(2035,1,1,tzinfo=timezone.utc)
    data=history(billing)
    assert data['available']==505 and data['wallet']['next_expiry'] is None


def test_refunding_expired_subscription_never_deducts_permanent_pack_twice(billing):
    buy_pack(billing);buy_month(billing)
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert history(billing)['available']==505
    assert send(billing,'subscription_payment_refunded',invoice(status='refunded',refunded_amount=500)).status_code==200
    assert history(billing)['available']==505
    assert [e for e in history(billing)['entries'] if e['event']=='reversal'][0]['amount']==0


def test_refund_after_expiry_only_reverses_already_used_subscription_credits(billing):
    buy_pack(billing);buy_month(billing);usage(billing,200,True)
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert balance(billing)==505
    assert send(billing,'subscription_payment_refunded',invoice(status='refunded',refunded_amount=500)).status_code==200
    assert balance(billing)==305


def test_partial_refund_then_expiry_then_full_refund_does_not_double_debit(billing):
    buy_pack(billing);buy_month(billing)
    assert send(billing,'subscription_payment_refunded',invoice(status='partial_refund',refunded_amount=250)).status_code==200
    assert balance(billing)==1005
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert history(billing)['available']==505
    assert send(billing,'subscription_payment_refunded',invoice(status='refunded',refunded_amount=500)).status_code==200
    assert balance(billing)==505


def test_refunded_hold_can_release_its_debt_after_period_end_without_minting_credits(billing):
    buy_month(billing);usage(billing,1000)
    assert send(billing,'subscription_payment_refunded',invoice(status='refunded',refunded_amount=500)).status_code==200
    assert balance(billing)==-995
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert release(billing) is True
    assert balance(billing)==5


def test_cancellation_preserves_current_period_until_its_end(billing):
    intent=buy_month(billing);cancelled=subscription('cancelled','2026-10-20T12:00:00Z')
    cancelled['attributes']['ends_at']='2026-11-19T12:00:00Z'
    assert send(billing,'subscription_cancelled',cancelled,custom(intent)).status_code==200
    assert balance(billing)==1005
    billing.clock=datetime(2026,11,19,12,tzinfo=timezone.utc)
    assert balance(billing)==5


def test_month_boundaries_follow_anniversary_and_handle_short_months():
    sub=SimpleNamespace(renews_at=None,ends_at=None)
    assert period_end(datetime(2028,1,31,12,tzinfo=timezone.utc),31,sub)==datetime(2028,2,29,12,tzinfo=timezone.utc)
    assert period_end(datetime(2028,2,29,12,tzinfo=timezone.utc),31,sub)==datetime(2028,3,31,12,tzinfo=timezone.utc)


def test_parallel_expiry_can_only_remove_each_lot_once(billing):
    buy_month(billing);billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    async def parallel():
        async def expire():
            async with billing.sessions() as db:
                value=await credits.lock_balance(db,'alice');await db.commit();return value
        assert await asyncio.gather(expire(),expire())==[5,5]
        async with billing.sessions() as db:
            rows=(await db.execute(select(CreditEntry).where(CreditEntry.event=='expire'))).scalars().all()
            assert len(rows)==1 and rows[0].amount==-1000
    asyncio.run(parallel())


def test_profile_balance_also_enforces_expiry_without_opening_credit_history(billing):
    buy_pack(billing);buy_month(billing)
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    response=billing.client.get('/api/auth/me',headers=headers())
    assert response.status_code==200 and response.json()['credits']==505
    response=billing.client.patch('/api/auth/me',headers=headers(),json={'display_name':'Creator'})
    assert response.status_code==200 and response.json()['credits']==505


def test_offline_sweep_expires_due_accounts_once(billing,monkeypatch):
    from scripts import expire_subscription_credits as sweep
    monkeypatch.setattr(sweep,'async_session',billing.sessions)
    monkeypatch.setattr(sweep,'now',lambda:billing.clock)
    buy_pack(billing);buy_month(billing)
    billing.clock=datetime(2026,11,20,tzinfo=timezone.utc)
    assert asyncio.run(sweep.expire_due())==1
    assert asyncio.run(sweep.expire_due())==0
    assert balance(billing)==505


def test_open_subscription_checkout_cannot_silently_change_tier(billing):
    checkout(billing,'monthly')
    response=billing.client.post('/api/payments/checkout',headers=headers(),json={
        'product_id':'monthly_plus','idempotency_key':'different-tier-key-001'})
    assert response.status_code==409
    assert balance(billing)==5
