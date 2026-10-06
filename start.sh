#!/bin/sh
set -e
# 1) create tables (once, before any worker starts, so workers never race)
python init_db.py
# 2) run the web server. --proxy-headers makes the real visitor IP visible behind the host's proxy.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" --proxy-headers --forwarded-allow-ips="*"
