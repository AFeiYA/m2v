"""Recoverable version removal. Finished videos remain owned and downloadable."""
from sqlalchemy import exists, select, update
from fastapi import HTTPException
from src.models import Task, VersionTrash, ExportJob


def live_task():
    return ~exists(select(VersionTrash.task_id).where(VersionTrash.task_id == Task.id))


async def trash_version(db, uid, task_id):
    task = (await db.execute(select(Task).where(Task.id == task_id, Task.user_id == uid))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, 'Version not found')
    await db.execute(update(Task).where(Task.id == task_id).values(progress=Task.progress, updated_at=Task.updated_at))
    if await db.get(VersionTrash, task_id):
        return
    # Lock render jobs before touching the account balance, as in task deletion.
    rows = (await db.execute(select(ExportJob).where(ExportJob.task_id == task_id).with_for_update())).scalars().all()
    from src.task_lifecycle import fail_task_and_refund
    await fail_task_and_refund(db, task_id, 'Version moved to Trash. Reserved credits returned.')
    from src.credits import finish
    for row in rows:
        if row.status in ('queued','running','uploading'):
            row.status = 'interrupted'
            row.run_token = None
            row.error = 'Version moved to Trash. Restore it before retrying.'
            await finish(db, uid, row.id, 'lyric_export', False)
    task.idempotency_key = None
    db.add(VersionTrash(task_id=task_id, user_id=uid))
    await db.commit()
