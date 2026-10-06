"""Business rules shared by the routers."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from models import EntryStatus, utcnow

# Which status changes are legal. Anything else is rejected with a 400.
ALLOWED_TRANSITIONS = {
    EntryStatus.waiting: {EntryStatus.called, EntryStatus.skipped, EntryStatus.noshow},
    EntryStatus.called: {EntryStatus.done, EntryStatus.skipped, EntryStatus.noshow},
    EntryStatus.done: {EntryStatus.waiting},       # recall
    EntryStatus.skipped: {EntryStatus.waiting},
    EntryStatus.noshow: {EntryStatus.waiting},
}


def next_position(db: Session, queue_id: int) -> int:
    """Next join-order number. Callers must hold the queue row lock (see routers)."""
    from sqlalchemy import func
    last = db.query(func.max(models.Entry.position)).filter(models.Entry.queue_id == queue_id).scalar()
    return (last or 0) + 1


def change_status(db: Session, entry: models.Entry, new_status: EntryStatus) -> None:
    old = entry.status
    if new_status not in ALLOWED_TRANSITIONS[old]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change an entry from '{old.value}' to '{new_status.value}'.",
        )

    now = utcnow()
    if new_status == EntryStatus.called:
        entry.called_at = now
        entry.completed_at = None
    elif new_status in (EntryStatus.done, EntryStatus.skipped, EntryStatus.noshow):
        entry.completed_at = now
    elif new_status == EntryStatus.waiting:          # recall: back of the line
        entry.called_at = None
        entry.completed_at = None
        entry.position = next_position(db, entry.queue_id)

    entry.status = new_status
    db.add(models.EntryHistory(
        entry_id=entry.id, queue_id=entry.queue_id,
        from_status=old.value, to_status=new_status.value, changed_at=now,
    ))


def minutes_per_person(db: Session, queue: models.Queue) -> int:
    """Estimated minutes per student.

    Uses the average real service time (called -> done) of the last 20 finished
    entries. Until 3 have finished, falls back to the teacher's manual estimate.
    """
    rows = (
        db.query(models.Entry.called_at, models.Entry.completed_at)
        .filter(
            models.Entry.queue_id == queue.id,
            models.Entry.status == EntryStatus.done,
            models.Entry.called_at.isnot(None),
            models.Entry.completed_at.isnot(None),
        )
        .order_by(models.Entry.completed_at.desc())
        .limit(20)
        .all()
    )
    # Clip to 30 s .. 60 min so one forgotten "Done" click can't wreck the average.
    durations = [min(max((end - start).total_seconds(), 30), 3600) for start, end in rows if end > start]
    if len(durations) < 3:
        return queue.wait_time_estimate or 5
    return max(1, round(sum(durations) / len(durations) / 60))
