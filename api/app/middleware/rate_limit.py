import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings

settings = get_settings()


class _SlidingWindowLimiter:
    """In-memory sliding-window limiter.

    Single-VM deployment (§1.4): no shared cache needed, an in-process
    structure is sufficient for 1-3 concurrent users.
    """

    def __init__(self, max_events: int, window_seconds: int = 60) -> None:
        self._max_events = max_events
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._events[key]
        while bucket and now - bucket[0] > self._window_seconds:
            bucket.popleft()
        if len(bucket) >= self._max_events:
            return False
        bucket.append(now)
        return True


login_limiter = _SlidingWindowLimiter(settings.login_rate_limit_per_minute)
extraction_limiter = _SlidingWindowLimiter(settings.extraction_rate_limit_per_minute)
request_limiter = _SlidingWindowLimiter(settings.request_rate_limit_per_minute)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client_key = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown"
        )

        if request.url.path == "/api/v1/auth/login" and request.method == "POST":
            if not login_limiter.allow(client_key):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Troppi tentativi di login, riprovare tra qualche minuto.",
                            "details": {},
                        }
                    },
                )
        elif request.url.path == "/api/v1/extract" and request.method == "POST":
            session_cookie = request.cookies.get("netstock_session", client_key)
            if not extraction_limiter.allow(session_cookie):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Limite di estrazioni al minuto raggiunto, riprovare a breve.",
                            "details": {},
                        }
                    },
                )
        else:
            session_cookie = request.cookies.get("netstock_session", client_key)
            if not request_limiter.allow(session_cookie):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Troppe richieste in questo minuto, rallentare.",
                            "details": {},
                        }
                    },
                )

        return await call_next(request)
