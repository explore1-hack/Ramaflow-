import csv
import hmac
import os
from io import StringIO
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
import schemas
import services
from database import get_db
from limiter import limiter
from models import EntryStatus

router = APIRouter(prefix="/admin", tags=["admin"])

# Optional: if set, only people who know this code can create teacher accounts.
INVITE_CODE = os.getenv("INVITE_CODE", "").strip()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _csv_safe(value) -> str:
    """Stop spreadsheet apps from running student input as a formula."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _fmt_dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------

@router.get("/registration-info")
def registration_info():
    return {"invite_required": bool(INVITE_CODE)}


@router.post("/register", response_model=schemas.AdminOut)
@limiter.limit("10/minute")
def register_admin(request: Request, payload: schemas.AdminCreate, db: Session = Depends(get_db)):
    if INVITE_CODE and not hmac.compare_digest((payload.invite_code or "").strip(), INVITE_CODE):
        raise HTTPException(status_code=403, detail="Invalid invite code")

    username = payload.username.strip()
    email = payload.email.strip().lower()

    # Case-insensitive username check so "Bob" and "bob" can't both exist.
    existing = (
        db.query(models.Admin)
        .filter((func.lower(models.Admin.username) == username.lower()) | (models.Admin.email == email))
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    admin = models.Admin(
        username=username,
        email=email,
        hashed_password=auth.hash_password(payload.password),
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:  # two people registering the same name at the same instant
        db.rollback()
        raise HTTPException(status_code=400, detail="Username or email already registered")
    db.refresh(admin)
    return admin


@router.post("/login", response_model=schemas.Token)
@limiter.limit("10/minute")
def login(request: Request, payload: schemas.AdminLogin, db: Session = Depends(get_db)):
    identifier = payload.identifier.strip()

    # Exact username/email first (keeps existing accounts working),
    # then fall back to a case-insensitive match.
    admin = (
        db.query(models.Admin)
        .filter((models.Admin.username == identifier) | (models.Admin.email == identifier.lower()))
        .first()
    )
    if not admin:
        admin = (
            db.query(models.Admin)
            .filter(func.lower(models.Admin.username) == identifier.lower())
            .first()
        )

    if not admin or not auth.verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username/email or password")
    return {"access_token": auth.create_access_token({"sub": str(admin.id)}), "token_type": "bearer"}


@router.get("/me", response_model=schemas.AdminOut)
def get_me(current_admin: models.Admin = Depends(auth.get_current_admin)):
    return current_admin


# ---------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------

def _get_owned_queue(db: Session, queue_id: int, admin: models.Admin, lock: bool = False) -> models.Queue:
    q = db.query(models.Queue).filter(models.Queue.id == queue_id)
    if lock:
        # SELECT ... FOR UPDATE: other requests touching this queue wait until we commit.
        # Keeps join / recall / call-next from racing each other (PostgreSQL).
        q = q.with_for_update()
    queue = q.first()
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")
    if queue.admin_id != admin.id:
        raise HTTPException(status_code=403, detail="Not your queue")
    return queue


def _lock_entry(db: Session, entry_id: int, admin: models.Admin):
    """Lock the entry's queue, then (re)read the entry so we act on fresh data."""
    entry = db.get(models.Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    queue = _get_owned_queue(db, entry.queue_id, admin, lock=True)
    db.refresh(entry)
    return entry, queue


@router.post("/queues", response_model=schemas.QueueOut)
def create_queue(
    payload: schemas.QueueCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(auth.get_current_admin),
):
    # Clean and de-duplicate fields (keeps order).
    fields = []
    for f in payload.fields:
        f = str(f).strip()
        if f and f not in fields:
            fields.append(f)

    if not fields:
        raise HTTPException(status_code=400, detail="Add at least one field.")
    if payload.unique_field not in fields:
        raise HTTPException(status_code=400, detail="Unique field must be one of the fields.")
    if payload.wait_time_estimate < 1:
        raise HTTPException(status_code=400, detail="Wait time must be at least 1 minute.")

    queue = models.Queue(
        admin_id=current_admin.id,
        name=payload.name.strip(),
        fields=fields,
        unique_field=payload.unique_field,
        wait_time_estimate=payload.wait_time_estimate,
    )
    db.add(queue)
    db.commit()
    db.refresh(queue)
    return queue


@router.get("/queues", response_model=List[schemas.QueueOut])
def list_my_queues(db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return (
        db.query(models.Queue)
        .filter(models.Queue.admin_id == current_admin.id)
        .order_by(models.Queue.id.desc())
        .all()
    )


@router.get("/queues/{queue_id}", response_model=schemas.QueueOut)
def get_my_queue(queue_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _get_owned_queue(db, queue_id, current_admin)


def _set_active(queue_id: int, active: bool, db: Session, admin: models.Admin) -> models.Queue:
    queue = _get_owned_queue(db, queue_id, admin, lock=True)
    queue.is_active = active
    db.commit()
    db.refresh(queue)
    return queue


# No DELETE on purpose: closing keeps the history.
@router.post("/queues/{queue_id}/close", response_model=schemas.QueueOut)
def close_queue(queue_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _set_active(queue_id, False, db, current_admin)


@router.post("/queues/{queue_id}/reopen", response_model=schemas.QueueOut)
def reopen_queue(queue_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _set_active(queue_id, True, db, current_admin)


@router.patch("/queues/{queue_id}/wait-time", response_model=schemas.QueueOut)
def update_wait_time(
    queue_id: int,
    payload: schemas.WaitTimeUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(auth.get_current_admin),
):
    if payload.wait_time_estimate < 1:
        raise HTTPException(status_code=400, detail="Wait time must be at least 1 minute.")
    queue = _get_owned_queue(db, queue_id, current_admin)
    queue.wait_time_estimate = payload.wait_time_estimate
    db.commit()
    db.refresh(queue)
    return queue


@router.get("/queues/{queue_id}/entries", response_model=List[schemas.EntryOut])
def list_entries(queue_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    _get_owned_queue(db, queue_id, current_admin)
    return (
        db.query(models.Entry)
        .filter(models.Entry.queue_id == queue_id)
        .order_by(models.Entry.position)
        .all()
    )


@router.get("/queues/{queue_id}/export")
def export_queue_entries(
    queue_id: int,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(auth.get_current_admin),
):
    queue = _get_owned_queue(db, queue_id, current_admin)
    entries = (
        db.query(models.Entry)
        .filter(models.Entry.queue_id == queue_id)
        .order_by(models.Entry.position.asc())
        .all()
    )

    output = StringIO()
    output.write("\ufeff")  # BOM so Excel reads UTF-8 names correctly
    writer = csv.writer(output)

    custom_fields = list(queue.fields or [])
    writer.writerow(["Position", "Status", "Joined At", "Called At"] + [_csv_safe(f) for f in custom_fields])

    for entry in entries:
        status = entry.status.value if hasattr(entry.status, "value") else entry.status
        row = [entry.position, status, _fmt_dt(entry.created_at), _fmt_dt(entry.called_at)]
        data = entry.data or {}
        for field in custom_fields:
            row.append(_csv_safe(data.get(field, "")))
        writer.writerow(row)

    filename = f"queue_{queue_id}_report.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------
# Entry actions
# ---------------------------------------------------------------------

def _change(db: Session, entry: models.Entry, new_status: EntryStatus, conflict_msg: str) -> models.Entry:
    try:
        services.change_status(db, entry, new_status)
        db.commit()
    except IntegrityError:
        # e.g. recall would create a second active entry with the same unique value
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict_msg)
    except ValueError as exc:  # invalid transition raised by services (if it does)
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid status change.")
    db.refresh(entry)
    return entry


def _apply(entry_id: int, new_status: EntryStatus, db: Session, admin: models.Admin) -> models.Entry:
    entry, _ = _lock_entry(db, entry_id, admin)
    return _change(db, entry, new_status, "That student already has an active spot in this queue.")


@router.post("/queues/{queue_id}/call-next", response_model=schemas.EntryOut)
def call_next(queue_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    """Call the student who has been waiting longest."""
    _get_owned_queue(db, queue_id, current_admin, lock=True)
    entry = (
        db.query(models.Entry)
        .filter(models.Entry.queue_id == queue_id, models.Entry.status == EntryStatus.waiting)
        .order_by(models.Entry.position)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="No one is waiting.")
    return _change(db, entry, EntryStatus.called, "Could not call this student. Please refresh and try again.")


@router.post("/entries/{entry_id}/call", response_model=schemas.EntryOut)
def call_entry(entry_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _apply(entry_id, EntryStatus.called, db, current_admin)


@router.post("/entries/{entry_id}/done", response_model=schemas.EntryOut)
def mark_done(entry_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _apply(entry_id, EntryStatus.done, db, current_admin)


@router.post("/entries/{entry_id}/skip", response_model=schemas.EntryOut)
def skip_entry(entry_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _apply(entry_id, EntryStatus.skipped, db, current_admin)


@router.post("/entries/{entry_id}/noshow", response_model=schemas.EntryOut)
def mark_noshow(entry_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    return _apply(entry_id, EntryStatus.noshow, db, current_admin)


@router.post("/entries/{entry_id}/recall", response_model=schemas.EntryOut)
def recall_entry(entry_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(auth.get_current_admin)):
    """Put a done/skipped/no-show entry back at the end of the waiting line."""
    return _apply(entry_id, EntryStatus.waiting, db, current_admin)
