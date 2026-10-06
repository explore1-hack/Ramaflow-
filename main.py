from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

import models  # noqa: F401
from database import IS_SQLITE, Base, engine
from limiter import limiter, rate_limit_handler
from routers import admin_router, user_router

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Local SQLite dev: create tables automatically.
# With PostgreSQL, tables are created by init_db.py (run by start.sh) so multiple
# workers don't race to create them.
if IS_SQLITE:
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="Queuer")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
# No CORS middleware: the pages and the API are served from the same origin.


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(admin_router.router)
app.include_router(user_router.router)


@app.get("/health", include_in_schema=False)
def health():
    """Used by the hosting platform to check the app and database are alive."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name)


@app.get("/", include_in_schema=False)
def page_login():
    return _page("admin_login.html")


@app.get("/register", include_in_schema=False)
def page_register():
    return _page("admin_register.html")


@app.get("/dashboard", include_in_schema=False)
def page_dashboard():
    return _page("admin_dashboard.html")


@app.get("/join", include_in_schema=False)
def page_join():
    return _page("join.html")


@app.get("/status", include_in_schema=False)
def page_status():
    return _page("status.html")
