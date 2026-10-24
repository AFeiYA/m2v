"""Read-only merchant configuration check; never creates a checkout or charge."""
import asyncio


def validate_release_policy(settings, products):
    """Fail closed when a deployment still carries an older commercial policy."""
    from fastapi import HTTPException
    expected = {('subscription', 999, 300), ('subscription', 1999, 800), ('subscription', 2999, 1500)}
    if len(products) != 3 or {(p.kind, p.price_cents, p.credits) for p in products.values()} != expected:
        raise HTTPException(503, 'Release requires the current three monthly subscription prices and credit amounts')
    rates = {'ALIGNMENT_CREDITS': 20, 'MOTION_EXPORT_CREDITS': 10,
             'MOTION_WEBCODECS_CREDITS': 10, 'NEW_USER_PERMANENT_CREDITS': 60, 'FREE_MONTHLY_QUOTA': 0}
    if any(getattr(settings, name) != amount for name, amount in rates.items()):
        raise HTTPException(503, 'Release usage/trial policy mismatch: alignment 20, Motion 10/10, welcome 60, free monthly 0 required')


async def check():
    from sqlalchemy import func, select
    from src.billing_config import configured
    from src.billing_models import BillingEvent, BillingCheckout
    from src.billing_provider import validate_product
    from src.database import async_session
    settings,products=configured()
    if settings.BILLING_PROVIDER=='paddle':
        validate_release_policy(settings, products)
        from src.paddle_provider import preflight
        from src.paddle_config import prefix
        await preflight(settings,products,release=True)
        async with async_session() as db:
            if settings.PADDLE_ENVIRONMENT == 'production':
                test_rows = (await db.execute(select(func.count()).select_from(BillingCheckout).where(
                    BillingCheckout.test_mode.is_(True)))).scalar_one()
                if test_rows:
                    from fastapi import HTTPException
                    raise HTTPException(503, 'Test purchases exist in this database. Use an isolated production database; do not carry sandbox balances live.')
            pending=(await db.execute(select(func.count()).select_from(BillingEvent).where(
                BillingEvent.resource_id.startswith(prefix(settings)),BillingEvent.status.in_(['pending','review'])))).scalar_one()
            rows=(await db.execute(select(BillingEvent).where(
                BillingEvent.resource_id.startswith(prefix(settings)),BillingEvent.status.in_(['pending','review']))
                .order_by(BillingEvent.created_at).limit(20))).scalars()
            for row in rows:
                print(f'Event {row.id}: status={row.status} attempts={row.attempts} next={row.next_attempt_at} reason={row.last_error}')
        print(f'Paddle {settings.PADDLE_ENVIRONMENT.upper()} configuration matches; pending/review events: {pending}')
        if pending:
            raise RuntimeError('Resolve pending/review billing events before launch')
        print('Configuration checks passed. Account verification and end-to-end acceptance still require sign-off.')
        return
    if settings.BILLING_PROVIDER=='stripe':
        from src.stripe_provider import preflight
        from src.stripe_payments import prefix
        await preflight(settings,products)
        async with async_session() as db:
            review=(await db.execute(select(func.count()).select_from(BillingEvent).where(
                BillingEvent.resource_id.startswith(prefix(settings)),BillingEvent.status.in_(['pending','review'])))).scalar_one()
        print(f'Stripe SANDBOX configuration matches; pending/review events: {review}')
        print('Mock tests do not replace real sandbox Checkout, renewal, refund and Tax acceptance.')
        return
    for product in products.values():
        await validate_product(settings,product)
        print(f'Product {product.id}: provider configuration matches')
    async with async_session() as db:
        prefix=f'{int(settings.LEMONSQUEEZY_TEST_MODE)}:{settings.LEMONSQUEEZY_STORE_ID}:'
        pending=(await db.execute(select(func.count()).select_from(BillingEvent).where(
            BillingEvent.status=='pending',BillingEvent.resource_id.startswith(prefix)))).scalar_one()
    print(f'Environment: {"TEST" if settings.LEMONSQUEEZY_TEST_MODE else "LIVE"}; pending inbox: {pending}')
    print('Preflight passed. Checkout, renewal, refund and restore acceptance still required.')


if __name__=='__main__':
    import argparse
    import os
    from pathlib import Path
    from dotenv import dotenv_values
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Read a private env file before loading backend configuration')
    parser.add_argument('--prepare', action='store_true', help='Enable validation flags in this read-only process only; does not enable a running server')
    args = parser.parse_args()
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_file():
            parser.error('Configuration file does not exist')
        os.environ.update({k:v for k,v in dotenv_values(config_path).items() if v is not None})
    if args.prepare:
        os.environ['BILLING_ENABLED'] = 'true'
        os.environ['PADDLE_LIVE_ENABLED'] = 'true'
    try:
        asyncio.run(check())
    except Exception as exc:
        from fastapi import HTTPException
        reason = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail,str) else 'Check backend configuration, products, database and pending events.'
        print('Billing preflight failed: ' + reason)
        raise SystemExit(1) from None
