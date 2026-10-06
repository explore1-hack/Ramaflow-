# Queuer

A no-login digital queue for schools and colleges. A teacher creates a queue and shares a
link/QR code; students join from their phones and watch their live position. History of
every student served, skipped, or marked no-show is stored permanently.

**Stack:** HTML/CSS/JS frontend (served by the app) · FastAPI backend · PostgreSQL database · polling every 5 s (no WebSockets)

## Features
- Teacher accounts (bcrypt + JWT), optional invite code; each teacher only sees their own queues
- Custom fields per queue + one **unique field** (e.g. Roll No.) to block duplicate joins (case-insensitive)
- Join by link/QR, no login; the browser remembers the student's spot if the tab is closed
- Live position and estimated wait; the estimate uses the **rolling average of real service times** (last 20), falling back to the teacher's manual value until 3 students are served
- Teacher controls: Call next, call, done, skip, no-show, recall; open/close queue (no delete, history is kept)
- Every status change is logged in `entry_history`

## Design decisions
| Problem | Solution |
|---|---|
| Two students join at the same instant | `SELECT ... FOR UPDATE` on the queue row so joins take turns; `UNIQUE(queue_id, position)` as a safety net |
| Same roll number twice | Check in code **plus** a partial unique index (only while waiting/called) so the database enforces it too |
| Invalid status changes | Explicit transition table in `services.py` |
| Polling cost | Status endpoint is one `COUNT` query; index on `(queue_id, status, position)` |
| Connection-pool deadlock under bursts | Session cleanup runs on the event loop; hot endpoints release their connection before the response is built |
| Abuse | Rate limiting (slowapi), input length limits, only the queue's own fields are stored |
| Secrets | App refuses to start in production without a strong `SECRET_KEY` |

## Run locally (SQLite, quickest)
```bash
pip install -r requirements.txt
export APP_ENV=development          # allows the built-in dev secret
uvicorn main:app --reload
```
Open http://localhost:8000 (API docs at /docs).

## Run like production (PostgreSQL + Docker)
```bash
docker compose up --build            # http://localhost:8000
```

## Tests
```bash
pip install -r requirements-dev.txt
pytest -q                                                    # SQLite: 17 pass, 2 concurrency tests skipped
docker compose up -d db
TEST_DATABASE_URL=postgresql://queuer:queuer@localhost:5432/queuer pytest -q   # PostgreSQL: all 19 run
```
The PostgreSQL run includes **100 simultaneous joins -> positions exactly 1..100** and **20 simultaneous joins with the same roll number -> exactly 1 succeeds**. CI (GitHub Actions) runs everything against PostgreSQL.

## Deploy (Render)
1. Push this folder to a GitHub repo.
2. Render dashboard -> **New -> Blueprint** -> select the repo (it reads `render.yaml`).
3. When asked, enter an `INVITE_CODE` (teachers need it to register), or leave blank for open registration.
4. After the first deploy, open the URL, register a teacher account, create a queue, share the link/QR.

Environment variables: `DATABASE_URL`, `SECRET_KEY` (32+ chars), `APP_ENV=production`, optional `INVITE_CODE`, `WEB_CONCURRENCY` (workers, default 2).

## Load test
```bash
QUEUE_ID=1 locust -f loadtest/locustfile.py --host http://localhost:8000
```
Record **your own** numbers from the deployed app before putting any on a resume.

## Known limitations
- Rate-limit counters are per worker (in memory), fine at this scale
- Polling means position updates lag by up to 5 s
- Tables are created with `create_all`; schema changes later need a migration tool (Alembic)
- Anyone with the link can join (by design: no student login); the unique field + browser memory reduce abuse but a determined person can still evade them
