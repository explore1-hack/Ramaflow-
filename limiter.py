import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Rate limits are counted per client IP. (Behind a proxy, uvicorn's --proxy-headers
# makes the "client IP" the real visitor, not the proxy.)
# Note: counters live in each worker's memory. That is fine for abuse protection at this scale.
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "1") == "1",
)


def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a minute and try again."},
    )
