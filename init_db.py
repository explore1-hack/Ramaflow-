"""Create tables. Run once before starting the server (start.sh does this)."""
from database import Base, engine
import models  # noqa: F401  (importing registers the tables)

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Database tables are ready.")
