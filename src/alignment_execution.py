"""Alignment liveness, separate from progress (long model calls need no progress).

New imports persist this lease atomically with their task/credit hold. Legacy
workers have no lease and are never expired based on an arbitrary task age.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
import asyncio
import threading

from sqlalchemy import exists, select, update

from src.models import AlignmentExecution, Task, TaskStatus
from src.utils import log

LEASE_SECONDS = 120
QUEUE_SECONDS = 1800
HEARTBEAT_SECONDS = 10
_token = ContextVar("alignment_execution_token", default=None)


def now():
    return datetime.now(timezone.utc)


def current_token():
    return _token.get()


def guard(task_id):
    query = select(AlignmentExecution.task_id).where(AlignmentExecution.task_id == task_id)
    token = _token.get()
    if token is None:
        return ~exists(query)  # Compatibility only for tasks without a managed lease.
    return exists(query.where(AlignmentExecution.token == token,
                              AlignmentExecution.phase == "running",
                              AlignmentExecution.lease_until > now()))


def sync_db(action):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from src.settings import get_settings

    async def run():
        engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                result = await action(db)
                await db.commit()
                return result
        finally:
            await engine.dispose()
    return asyncio.run(run())


@contextmanager
def heartbeat(task_id, token, phase):
    """Independent thread keeps leases alive during blocking GPU/model inference."""
    stopped = threading.Event()

    async def renew(db):
        changed = await db.execute(update(AlignmentExecution).where(
            AlignmentExecution.task_id == task_id, AlignmentExecution.token == token,
            AlignmentExecution.phase == phase, AlignmentExecution.lease_until > now(),
        ).values(lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
        return bool(changed.rowcount)

    def beat():
        while not stopped.wait(HEARTBEAT_SECONDS):
            try:
                if not sync_db(renew):
                    break
            except Exception:
                log.warning("Alignment heartbeat unavailable: task=%s", task_id)

    thread = threading.Thread(target=beat, daemon=True, name=f"AlignmentHeartbeat-{task_id[:8]}")
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def managed_worker(function):
    @wraps(function)
    def run(*args, **kwargs):
        task_id = kwargs.get("task_id", args[0] if args else None)
        config = kwargs.get("config_dict", args[3] if len(args) > 3 else None) or {}
        token = config.get("_execution_token")
        if token is None:
            # A queued legacy invocation must not execute a newly managed task.
            async def legacy(db):
                return await db.get(AlignmentExecution, task_id) is None
            if not sync_db(legacy):
                return {"status": "interrupted", "task_id": task_id}
            return function(*args, **kwargs)

        async def claim(db):
            changed = await db.execute(update(AlignmentExecution).where(
                AlignmentExecution.task_id == task_id, AlignmentExecution.token == token,
                AlignmentExecution.phase == "queued", AlignmentExecution.lease_until > now(),
                exists(select(Task.id).where(Task.id == task_id, Task.status == TaskStatus.PENDING)),
            ).values(phase="running", lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
            return bool(changed.rowcount)
        if not sync_db(claim):
            return {"status": "interrupted", "task_id": task_id}
        context = _token.set(token)
        try:
            with heartbeat(task_id, token, "running"):
                return function(*args, **kwargs)
        finally:
            _token.reset(context)
    return run


async def reconcile(db, user_id):
    """On owner activity, release expired holds once; never automatically rerun AI."""
    deadline = now()
    ids = (await db.execute(select(Task.id).join(
        AlignmentExecution, AlignmentExecution.task_id == Task.id,
    ).where(Task.user_id == user_id,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]),
            AlignmentExecution.phase.in_(["preparing", "queued", "running"]),
            AlignmentExecution.lease_until <= deadline).order_by(Task.id).limit(100))).scalars().all()
    # Each recovery is its own short transaction. Holding one user's balance
    # while locking the next task would invert normal Task -> balance ordering.
    from src import api_server
    for task_id in ids:
        async with api_server.async_session() as recovery:
            locked = await recovery.execute(update(Task).where(
                Task.id == task_id, Task.user_id == user_id,
                Task.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]),
            ).values(progress=Task.progress, updated_at=Task.updated_at))
            if locked.rowcount:
                expired = await recovery.execute(update(AlignmentExecution).where(
                    AlignmentExecution.task_id == task_id,
                    AlignmentExecution.phase.in_(["preparing", "queued", "running"]),
                    AlignmentExecution.lease_until <= deadline,
                ).values(phase="expired"))
                if expired.rowcount:
                    from src.task_lifecycle import fail_task_and_refund
                    await fail_task_and_refund(recovery, task_id,
                        "Alignment processing was interrupted. Reserved credits returned; please import again.")
            await recovery.commit()
        # Authentication eagerly loads User.tasks. Refresh that request's cached
        # objects after the separate recovery transaction commits.
        await db.get(Task, task_id, populate_existing=True)
    if ids:
        from src.models import User
        await db.get(User, user_id, populate_existing=True)
