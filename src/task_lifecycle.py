"""Shared, idempotent failure handling for Celery and local worker threads."""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Task, TaskStatus, TaskStep, User


async def fail_task_and_refund(db: AsyncSession, task_id: str, error: str) -> bool:
    """Claim the failure once and refund its reserved credits in the same transaction.

    The caller commits the transaction. Concurrent/repeated failure handlers cannot
    refund a task that has already failed or completed.
    """
    result = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
        .values(
            status=TaskStatus.FAILED,
            current_step=TaskStep.ERROR,
            error_message=error,
            completed_at=datetime.now(timezone.utc),
        )
        .returning(Task.user_id, Task.cost_credits)
    )
    claimed = result.first()
    if claimed is None:
        return False
    await db.execute(
        update(User).where(User.id == claimed.user_id)
        .values(credits=User.credits + claimed.cost_credits)
    )
    return True


def record_task_failure(task_id: str, error: str) -> None:
    """Synchronous worker entrypoint; never reuse a pool across event loops."""
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from src.settings import get_settings

    async def record():
        engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await fail_task_and_refund(db, task_id, error)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(record())
