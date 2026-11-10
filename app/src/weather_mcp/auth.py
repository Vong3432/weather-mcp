import json
import logging
import time
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

from weather_mcp.tokens import TokenStore

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
PUBLIC_PATHS = {"/health"}

current_consumer: ContextVar[str | None] = ContextVar("current_consumer", default=None)


class RateLimiter:
    """Global token bucket for the instance. Cloud Run has no built-in throttle, and max-instances is
    capped, so this bounds total load on the server and on Open-Meteo's free tier."""

    def __init__(self, rate_per_second: float = 10, burst: int = 20):
        self.rate = rate_per_second
        self.burst = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self._tokens = min(self.burst, self._tokens + (now - self._updated) * self.rate)
        self._updated = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True


class TokenAuthMiddleware:
    """Accepts a consumer token as `Authorization: Bearer <t>` (VS Code) or as `/mcp/<t>` (ChatGPT,
    which cannot send custom headers). Path tokens are stripped so the MCP app only ever sees /mcp."""

    def __init__(self, app: ASGIApp, tokens: TokenStore, limiter: RateLimiter | None = None):
        self.app = app
        self.tokens = tokens
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        if not self.limiter.allow():
            await _respond(send, 429, {"error": "rate_limited"})
            return

        path = scope["path"].rstrip("/")
        token = None
        if path.startswith(MCP_PATH + "/"):
            token = path[len(MCP_PATH) + 1 :]
            scope = {**scope, "path": MCP_PATH, "raw_path": MCP_PATH.encode()}
        elif path == MCP_PATH:
            token = _bearer(scope)
        else:
            await _respond(send, 404, {"error": "not_found"})
            return

        consumer = self.tokens.consumer_for(token)
        if consumer is None:
            log.info("Rejected request: missing or invalid token")
            await _respond(send, 401, {"error": "invalid_token"})
            return

        reset = current_consumer.set(consumer)
        try:
            await self.app(scope, receive, send)
        finally:
            current_consumer.reset(reset)


def _bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, credentials = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and credentials:
                return credentials.strip()
    return None


async def _respond(send: Send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": payload})
