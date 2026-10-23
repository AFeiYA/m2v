"""Recover sandbox events after a restart or transient provider failure."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from sqlalchemy import select
from src.billing_models import BillingEvent
from src.paddle_config import PREFIX
from src.paddle_service import process_inbox

log = logging.getLogger('m2v')


async def drain(settings, sessions, limit=20):
    async with sessions() as db:
        ids = (await db.execute(select(BillingEvent.id).where(BillingEvent.status == 'pending',
            BillingEvent.resource_id.startswith(PREFIX)).order_by(BillingEvent.attempts, BillingEvent.created_at).limit(limit))).scalars().all()
    completed = 0
    for eid in ids:
        async with sessions() as db:
            try:
                completed += int(await process_inbox(db, eid, settings))
            except Exception:
                log.warning('Paddle event pending retry: %s', eid)
    return completed


@asynccontextmanager
async def lifecycle():
    from src.settings import get_settings
    from src.billing_config import configured
    from src.database import async_session
    settings = get_settings()
    task = None
    if settings.BILLING_ENABLED and settings.BILLING_PROVIDER == 'paddle':
        try:
            configured()
        except Exception:
            log.warning('Paddle sandbox worker not started: billing configuration is incomplete')
        else:
            async def loop():
                while True:
                    try:
                        await drain(settings, async_session)
                    except Exception:
                        log.warning('Paddle sandbox inbox scan failed; will retry')
                    await asyncio.sleep(10)
            task = asyncio.create_task(loop(), name='paddle-sandbox-inbox')
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
