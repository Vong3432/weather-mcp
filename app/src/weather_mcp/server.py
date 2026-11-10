import logging
import os
from typing import Annotated

import httpx
import uvicorn
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from weather_mcp import forecast, geocode
from weather_mcp.auth import TokenAuthMiddleware, current_consumer
from weather_mcp.tokens import TokenStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("weather_mcp")

mcp = MCPServer(
    name="weather",
    title="Weather",
    instructions=(
        "Daily weather forecasts for a place on a given date, today up to 15 days ahead. "
        "If the user has not said which date they want, ask them before calling get_weather."
    ),
)

_http = httpx.AsyncClient(timeout=httpx.Timeout(10.0), headers={"User-Agent": "weather-mcp/0.1"})


@mcp.tool(
    title="Get weather",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True),
)
async def get_weather(
    location: Annotated[
        str,
        Field(description="City, region or country name, e.g. 'Tokyo', 'Bavaria', 'Japan'. A country resolves to its capital."),
    ],
    date: Annotated[
        str,
        Field(
            description=(
                "Date in YYYY-MM-DD, from today up to 15 days ahead in the location's local time. "
                "Convert relative dates like 'tomorrow' yourself. If the user did not specify a date, "
                "ask them for it; do not assume today."
            )
        ),
    ],
    units: Annotated[forecast.Units, Field(description="'metric' (°C, mm, km/h) or 'imperial' (°F, in, mph).")] = "metric",
) -> forecast.DailyWeather:
    """Get the daily weather forecast (condition, min/max temperature, precipitation, wind) for a place on a date.

    Only today and future dates up to 15 days ahead are supported; past dates are rejected.
    If the user did not say which date they want, ask them before calling this tool.
    """
    try:
        day = forecast.parse_date(date)
        place = await geocode.resolve(_http, location)
        forecast.check_date(day, place)
        result = await forecast.daily_weather(_http, place, day, units, requested_location=location)
    except (geocode.LocationNotFound, forecast.DateOutOfRange) as e:
        raise ToolError(str(e)) from None
    except httpx.HTTPError as e:
        log.warning("Open-Meteo request failed: %s", e)
        raise ToolError("The weather service is temporarily unavailable. Please try again shortly.") from None

    log.info("get_weather consumer=%s location=%r date=%s", current_consumer.get(), location, date)
    return result


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(tokens: TokenStore | None = None):
    # host="0.0.0.0" opts out of the SDK's localhost-only DNS-rebinding guard; requests arrive via Cloud Run's proxy.
    app = mcp.streamable_http_app(json_response=True, stateless_http=True, host="0.0.0.0")
    return TokenAuthMiddleware(app, tokens or TokenStore.from_env())


def main() -> None:
    # access_log=False: ChatGPT's URL carries the token (/mcp/<token>), so request paths must never be logged.
    uvicorn.run(
        create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), proxy_headers=True, access_log=False
    )


if __name__ == "__main__":
    main()
