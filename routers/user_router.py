from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
import services
from database import get_db
from limiter import limiter
from models import ACTIVE_STATUSES, EntryStatus

router = APIRouter(tags=["user"])

MAX_VALUE_LENGTH = 100


def _release_and_return(db: Session, result):
    """Give the DB connection back to the pool BEFORE returning.

    FastAPI turns the return value into a response in the same worker-thread pool that
    runs the endpoints. If we kept the connection until then, a burst of requests could
    hold all connections while waiting for a free thread, and the threads would be waiting
    for connections. Returning a plain pydantic object and closing early avoids that.
    """
    db.close()
    return result


@router.get("/queues/{queue_id}", response_model=schemas.QueueOut)
def get_queue_public(queue_id: int, db: Session = Depends(get_db)):
    queue = db.query(models.Queue).filter(models.Queue.id == queue_id, models.Queue.is_active.is_(True)).first()
    if not queue:
        raise HTTPException(status_code=404, detail="This queue is closed or does not exist.")
    return queue


def _clean_values(queue: models.Queue, data: dict) -> dict:
    """Keep only the queue's own fields, trimmed and length-limited. Extra keys are dropped."""
    cleaned, missing = {}, []
    for field in queue.fields:
        value = str(data.get(field, "")).strip()
        if not value:
            missing.append(field)
        elif len(value) > MAX_VALUE_LENGTH:
            raise HTTPException(status_code=400, detail=f"'{field}' is too long (max {MAX_VALUE_LENGTH} characters).")
        cleaned[field] = value
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")
    return cleaned


@router.post("/queues/{queue_id}/join", response_model=schemas.EntryOut)
# Generous on purpose: a whole class often shares one campus Wi-Fi IP address.
@limiter.limit("120/minute")
def join_queue(request: Request, queue_id: int, payload: schemas.EntryJoin, db: Session = Depends(get_db)):
    for _attempt in range(3):
        # Lock the queue row: simultaneous joins now take turns (PostgreSQL), so each
        # one sees the previous student's entry and gets the next free position.
        queue = (
            db.query(models.Queue)
            .filter(models.Queue.id == queue_id, models.Queue.is_active.is_(True))
            .with_for_update()
            .first()
        )
        if not queue:
            raise HTTPException(status_code=404, detail="This queue is closed or does not exist.")

        values = _clean_values(queue, payload.data)
        unique_value = values[queue.unique_field].upper()   # "21cs01" and "21CS01" are the same person

        duplicate = (
            db.query(models.Entry.id)
            .filter(
                models.Entry.queue_id == queue_id,
                models.Entry.unique_value == unique_value,
                models.Entry.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail=f"This {queue.unique_field} is already in the queue.")

        entry = models.Entry(
            queue_id=queue_id,
            data=values,
            unique_value=unique_value,
            status=EntryStatus.waiting,
            position=services.next_position(db, queue_id),
        )
        db.add(entry)
        db.flush()  # get entry.id for the history row
        db.add(models.EntryHistory(entry_id=entry.id, queue_id=queue_id, from_status=None, to_status="waiting"))
        try:
            db.commit()
        except IntegrityError:
            # The database safety nets (unique position / unique active value) caught a race
            # that slipped past the lock (e.g. on SQLite). Retry: the next pass will either
            # return a clean 409 or pick a fresh position.
            db.rollback()
            continue
        db.refresh(entry)
        return _release_and_return(db, schemas.EntryOut.model_validate(entry))

    raise HTTPException(status_code=503, detail="The queue is very busy. Please try again.")


@router.get("/entries/{entry_id}/status", response_model=schemas.EntryStatusOut)
def entry_status(entry_id: int, db: Session = Depends(get_db)):
    """Polled by the student's browser every few seconds, so it must stay cheap."""
    entry = db.get(models.Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    queue = db.get(models.Queue, entry.queue_id)

    position_in_queue = people_ahead = estimate = 0
    if entry.status == EntryStatus.waiting:
        # One COUNT query instead of loading every waiting entry into Python.
        people_ahead = (
            db.query(func.count(models.Entry.id))
            .filter(
                models.Entry.queue_id == entry.queue_id,
                models.Entry.status == EntryStatus.waiting,
                models.Entry.position < entry.position,
            )
            .scalar()
        )
        position_in_queue = people_ahead + 1
        estimate = people_ahead * services.minutes_per_person(db, queue)

    return _release_and_return(db, schemas.EntryStatusOut(
        id=entry.id,
        queue_id=entry.queue_id,
        queue_name=queue.name,
        status=entry.status.value,
        position_in_queue=position_in_queue,
        people_ahead=people_ahead,
        estimated_wait_minutes=estimate,
    ))
