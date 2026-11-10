from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel

from weather_mcp.cache import TTLCache
from weather_mcp.geocode import Place
from weather_mcp.wmo_codes import describe

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_DAYS_AHEAD = 15  # Open-Meteo serves 16 forecast days: today + 15

Units = Literal["metric", "imperial"]

_UNIT_PARAMS = {
    "metric": {},
    "imperial": {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"},
}
_UNIT_LABELS = {
    "metric": {"temperature": "°C", "precipitation": "mm", "wind_speed": "km/h"},
    "imperial": {"temperature": "°F", "precipitation": "in", "wind_speed": "mph"},
}
_DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max"

_cache = TTLCache(ttl_seconds=30 * 60)


class DateOutOfRange(Exception):
    pass


class DailyWeather(BaseModel):
    requested_location: str
    resolved_location: str
    note: str | None
    latitude: float
    longitude: float
    timezone: str
    date: str
    condition: str
    temperature_min: float | None
    temperature_max: float | None
    precipitation_sum: float | None
    precipitation_probability_max: int | None
    wind_speed_max: float | None
    units: dict[str, str]


def allowed_window(timezone: str, now: datetime | None = None) -> tuple[date, date]:
    """Today through today + MAX_DAYS_AHEAD, in the location's local date."""
    tz = ZoneInfo(timezone)
    today = (now or datetime.now(tz)).astimezone(tz).date()
    return today, today + timedelta(days=MAX_DAYS_AHEAD)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise DateOutOfRange(f"'{value}' is not a valid date. Use YYYY-MM-DD.") from None


def check_date(day: date, place: Place, now: datetime | None = None) -> None:
    first, last = allowed_window(place.timezone, now)
    if not first <= day <= last:
        raise DateOutOfRange(
            f"{day.isoformat()} is outside the supported range for {place.name} "
            f"(local time): only {first.isoformat()} to {last.isoformat()} is available. "
            "Past dates are not supported."
        )


async def daily_weather(
    client: httpx.AsyncClient, place: Place, day: date, units: Units, requested_location: str
) -> DailyWeather:
    key = (place.latitude, place.longitude, day, units)
    daily = _cache.get(key)
    if daily is None:
        params = {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "daily": _DAILY,
            "timezone": place.timezone,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            **_UNIT_PARAMS[units],
        }
        resp = await client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
        daily = resp.json()["daily"]
        _cache.set(key, daily)

    def first(field: str):
        values = daily.get(field) or [None]
        return values[0]

    note = None
    # City-states ("Singapore", "Hong Kong") resolve to themselves, so there is nothing to explain.
    if place.resolved_from_country and place.name.casefold() != requested_location.strip().casefold():
        note = f"'{requested_location}' is a country; showing weather for its capital, {place.name}".rstrip(".") + "."

    return DailyWeather(
        requested_location=requested_location,
        resolved_location=place.label,
        note=note,
        latitude=place.latitude,
        longitude=place.longitude,
        timezone=place.timezone,
        date=day.isoformat(),
        condition=describe(first("weather_code")),
        temperature_min=first("temperature_2m_min"),
        temperature_max=first("temperature_2m_max"),
        precipitation_sum=first("precipitation_sum"),
        precipitation_probability_max=first("precipitation_probability_max"),
        wind_speed_max=first("wind_speed_10m_max"),
        units=_UNIT_LABELS[units],
    )
