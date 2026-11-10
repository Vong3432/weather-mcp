import httpx
import pytest

from weather_mcp.auth import RateLimiter
from weather_mcp.server import create_app
from weather_mcp.tokens import TokenStore

TOKENS = TokenStore(static_json='{"alice": "tok_alice", "bob": "tok_bob"}')
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18"}


async def request(method: str, path: str, headers: dict | None = None) -> httpx.Response:
    app = create_app(TOKENS)
    # ASGITransport does not run lifespan, and the MCP session manager needs it.
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            if method == "GET":
                return await client.get(path)
            return await client.post(path, json=LIST_TOOLS, headers=HEADERS | (headers or {}))


async def test_health_is_public():
    resp = await request("GET", "/health")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "path,extra_headers",
    [("/mcp", {}), ("/mcp", {"authorization": "Bearer wrong"}), ("/mcp/wrong", {}), ("/mcp/", {})],
)
async def test_rejects_missing_or_invalid_token(path, extra_headers):
    resp = await request("POST", path, extra_headers)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "path,extra_headers",
    [("/mcp", {"authorization": "Bearer tok_alice"}), ("/mcp/tok_bob", {}), ("/mcp/tok_bob/", {})],
)
async def test_accepts_bearer_or_path_token(path, extra_headers):
    resp = await request("POST", path, extra_headers)
    assert resp.status_code == 200
    assert resp.json()["result"]["tools"][0]["name"] == "get_weather"


async def test_unknown_path_is_404():
    resp = await request("GET", "/admin")
    assert resp.status_code == 404


def test_rate_limiter_allows_burst_then_blocks():
    limiter = RateLimiter(rate_per_second=0.001, burst=3)
    assert [limiter.allow() for _ in range(4)] == [True, True, True, False]
