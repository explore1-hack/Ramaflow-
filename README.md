# Ramaflow

A lightweight digital queue for schools and colleges. A teacher creates a queue and shares a link or QR code. Students join from their phones (no sign-up), see their live position and estimated wait, and the teacher calls them one by one from a dashboard.

## Live demo

**Deployed link:** https://ramaflow.onrender.com/

> Hosted on Render. If the site has been idle, the first request can take up to a minute to wake up.

## Features

- **Teacher dashboard:** create queues, pick the details students must provide (Name, Roll No., Class, Division, Phone), call next, mark Done / Skip / No-show, recall, set wait time, export CSV.
- **Student side:** join by link or QR, validated form, live position and estimated wait, "your turn" alert.
- **Safe by default:** teacher login (JWT), invite code for registration, rate limiting, duplicate-join protection, server-side input validation.
- **Permanent history:** every status change is stored in the database.
- **Simple live updates:** polling every 5 seconds (no WebSockets).

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, FastAPI, Uvicorn |
| Database | PostgreSQL (SQLite for local development) |
| Testing | pytest |

## Project structure

```
Ramaflow/
├── routers/            admin_router.py, user_router.py
├── static/             HTML pages, config.js, presets.js, style.css
├── tests/              pytest tests
├── auth.py             login tokens and password hashing
├── database.py         database connection
├── entry_rules.py      validation of student input
├── limiter.py          rate limiting
├── main.py             app setup and page routes
├── models.py           database tables
├── schemas.py          request / response validation
├── services.py         queue rules (status changes, wait time)
├── init_db.py          creates the tables
└── start.sh            production start command
```

## Run locally

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

export APP_ENV=development        # Windows: set APP_ENV=development
uvicorn main:app --reload
```

Open http://localhost:8000 and register a teacher account. Without `DATABASE_URL`, a local SQLite file (`queuer.db`) is created automatically.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | `development` or `production` | `production` |
| `SECRET_KEY` | Signs login tokens (32+ characters, **required in production**) | none |
| `DATABASE_URL` | PostgreSQL connection string | local SQLite file |
| `INVITE_CODE` | If set, teachers need this code to register | empty |
| `RATE_LIMIT_ENABLED` | `0` turns rate limiting off | `1` |
| `STRICT_ENTRY_RULES` | `0` treats every student field as plain text | `1` |

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment

Production runs `start.sh`, which creates the tables and then starts Uvicorn. Set `SECRET_KEY` and `DATABASE_URL` in the host's environment settings. `render.yaml` is included for Render.

## How it works

1. The teacher logs in, creates a queue and shares the join link or QR code.
2. Students open the link, fill the form and get a place in the line.
3. The teacher calls the next student; the student's phone shows the turn.
