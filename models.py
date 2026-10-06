import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, JSON, String,
    UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from database import Base


def utcnow() -> datetime:
    """Current UTC time (naive, so it matches the DateTime columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EntryStatus(str, enum.Enum):
    waiting = "waiting"
    called = "called"
    done = "done"
    skipped = "skipped"
    noshow = "noshow"


ACTIVE_STATUSES = (EntryStatus.waiting, EntryStatus.called)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    queues = relationship("Queue", back_populates="admin")


class Queue(Base):
    __tablename__ = "queues"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    fields = Column(JSON, nullable=False)                # e.g. ["Name", "Roll No."]
    unique_field = Column(String(50), nullable=False)    # e.g. "Roll No." (duplicate-join key)
    wait_time_estimate = Column(Integer, default=5)      # minutes; fallback until real data exists
    is_active = Column(Boolean, default=True)            # False = closed to new joins
    created_at = Column(DateTime, default=utcnow)

    admin = relationship("Admin", back_populates="queues")
    entries = relationship("Entry", back_populates="queue")


class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, index=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False)
    data = Column(JSON, nullable=False)
    unique_value = Column(String(100), nullable=False)
    status = Column(Enum(EntryStatus), default=EntryStatus.waiting, nullable=False)
    position = Column(Integer, nullable=False)           # join order (FIFO)
    created_at = Column(DateTime, default=utcnow)
    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)       # when done / skipped / no-show

    queue = relationship("Queue", back_populates="entries")

    __table_args__ = (
        # Safety net 1: two entries in one queue can never share a position.
        UniqueConstraint("queue_id", "position", name="uq_entry_queue_position"),
        # Safety net 2: the same unique value (e.g. roll no.) cannot be in the line twice.
        # A *partial* unique index: it only applies while the entry is waiting/called,
        # so a student can rejoin after being served.
        Index(
            "uq_entry_active_unique_value", "queue_id", "unique_value", unique=True,
            sqlite_where=text("status IN ('waiting','called')"),
            postgresql_where=text("status IN ('waiting','called')"),
        ),
        # Speeds up the hot path: "how many waiting entries are ahead of me?"
        Index("ix_entry_queue_status_position", "queue_id", "status", "position"),
    )


class EntryHistory(Base):
    """Append-only log of every status change: the permanent audit trail."""
    __tablename__ = "entry_history"

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False, index=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False, index=True)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    changed_at = Column(DateTime, default=utcnow, nullable=False)
