"""Recover durable Paddle events in both standalone FastAPI and Gradio mounts."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging
from weakref import WeakKeyDictionary
from sqlalchemy import select, or_
from src.billing_models import BillingEvent
from src.paddle_config import prefix
from src.paddle_service import process_inbox

log = logging.getLogger('m2v')
_workers = WeakKeyDictionary()


async def drain(settings, sessions, limit=20):
    async with sessions() as db:
        ids = (await db.execute(select(BillingEvent.id).where(BillingEvent.status == 'pending',
            or_(BillingEvent.next_attempt_at.is_(None), BillingEvent.next_attempt_at <= datetime.now(timezone.utc)),
            BillingEvent.resource_id.startswith(prefix(settings))).order_by(BillingEvent.attempts, BillingEvent.created_at).limit(limit))).scalars().all()
    completed = 0
    for eid in ids:
        async with sessions() as db:
            try:
                completed += int(await process_inbox(db, eid, settings))
            except Exception:
                log.warning('Paddle event pending retry: %s', eid)
    return completed


def ensure_worker(settings, sessions):
    """Once per ASGI loop; also called by payment routes when Gradio skips lifespan."""
    loop = asyncio.get_running_loop()
    task = _workers.get(loop)
    if task and not task.done():
        return task
    async def run():
        while True:
            # Webhook acknowledgments never wait on remote API reads. Initial
            # recovery is deferred too, including when started by the webhook.
            await asyncio.sleep(10)
            try:
                await drain(settings, sessions)
            except Exception:
                log.error('Paddle inbox scan failed; recovery will retry')
    task = asyncio.create_task(run(), name='paddle-inbox')
    _workers[loop] = task
    def finished(completed):
        if _workers.get(loop) is completed:
            _workers.pop(loop, None)
    task.add_done_callback(finished)
    return task


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
            log.warning('Paddle worker not started: billing configuration is incomplete')
        else:
            task = ensure_worker(settings, async_session)
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
