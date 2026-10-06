import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import models
from database import get_db

APP_ENV = os.getenv("APP_ENV", "production").lower()

# The secret signs login tokens. If it leaks or is guessable, anyone can forge an admin login.
# So in production the app REFUSES to start without a strong one.
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if APP_ENV == "development":
        SECRET_KEY = "dev-only-secret-never-use-in-production"
    else:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
elif APP_ENV != "development" and len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY is too short; use at least 32 characters.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_admin(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.Admin:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id = int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        raise unauthorized

    admin = db.get(models.Admin, admin_id)
    if admin is None:
        raise unauthorized
    return admin
