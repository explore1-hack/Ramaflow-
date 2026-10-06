import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Local default: a SQLite file so the project runs out of the box.
# Production: set DATABASE_URL to a PostgreSQL connection string.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./queuer.db")

# Hosts like Render/Heroku hand out "postgres://..." or "postgresql://...". Newer SQLAlchemy
# versions pick a different driver for those, so we always name the driver we ship (psycopg2).
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len(_prefix):]
        break

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # timeout: wait for the write lock instead of failing instantly with "database is locked"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
        pool_pre_ping=True,   # drop dead connections (hosted DBs close idle ones)
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# NOTE: this is deliberately `async def`. The endpoints are normal (sync) functions that run
# in a worker-thread pool. If the cleanup below were a sync generator it would ALSO need a free
# worker thread; under a burst of requests every thread could be waiting for a DB connection
# while the connections wait for a thread to close them: a deadlock. Running the (quick)
# cleanup on the event loop avoids that.
async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
