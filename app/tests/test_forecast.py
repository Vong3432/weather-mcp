from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from weather_mcp import forecast
from weather_mcp.geocode import Place

TOKYO = Place("Tokyo", "Japan", "JP", 35.69, 139.69, "Asia/Tokyo", resolved_from_country="Japan")
HONOLULU = Place("Honolulu", "United States", "US", 21.3, -157.86, "Pacific/Honolulu")

# 2026-11-10 20:00 UTC is already 2026-11-11 in Tokyo but still 2026-11-10 in Honolulu.
NOW = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)


def test_window_uses_location_local_date():
    assert forecast.allowed_window("Asia/Tokyo", NOW) == (date(2026, 11, 11), date(2026, 11, 26))
    assert forecast.allowed_window("Pacific/Honolulu", NOW) == (date(2026, 11, 10), date(2026, 11, 25))


@pytest.mark.parametrize("day", [date(2026, 11, 11), date(2026, 11, 26)])
def test_window_edges_accepted(day):
    forecast.check_date(day, TOKYO, NOW)


@pytest.mark.parametrize("day", [date(2026, 11, 10), date(2026, 11, 27)])
def test_outside_window_rejected(day):
    with pytest.raises(forecast.DateOutOfRange, match="2026-11-11 to 2026-11-26"):
        forecast.check_date(day, TOKYO, NOW)


def test_same_utc_moment_today_differs_by_location():
    forecast.check_date(date(2026, 11, 10), HONOLULU, NOW)
    with pytest.raises(forecast.DateOutOfRange):
        forecast.check_date(date(2026, 11, 10), TOKYO, NOW)


@pytest.mark.parametrize("bad", ["tomorrow", "11/12/2026", ""])
def test_parse_date_rejects_non_iso(bad):
    with pytest.raises(forecast.DateOutOfRange, match="YYYY-MM-DD"):
        forecast.parse_date(bad)


@respx.mock
async def test_daily_weather_maps_response_and_units():
    route = respx.get(forecast.FORECAST_URL).respond(
        json={
            "daily": {
                "time": ["2026-11-12"],
                "weather_code": [61],
                "temperature_2m_max": [60.1],
                "temperature_2m_min": [45.0],
                "precipitation_sum": [0.2],
                "precipitation_probability_max": [70],
                "wind_speed_10m_max": [9.5],
            }
        }
    )
    async with httpx.AsyncClient() as client:
        result = await forecast.daily_weather(client, TOKYO, date(2026, 11, 12), "imperial", requested_location="Japan")

    params = route.calls.last.request.url.params
    assert params["temperature_unit"] == "fahrenheit"
    assert params["start_date"] == params["end_date"] == "2026-11-12"
    assert params["timezone"] == "Asia/Tokyo"
    assert result.condition == "Slight rain"
    assert result.temperature_max == 60.1
    assert result.units["temperature"] == "°F"
    assert result.note == "'Japan' is a country; showing weather for its capital, Tokyo."


@respx.mock
@pytest.mark.parametrize(
    "place,requested,expected",
    [
        (Place("Hong Kong", "Hong Kong", "HK", 22.3, 114.2, "Asia/Hong_Kong", resolved_from_country="Hong Kong"), "Hong Kong", None),
        (
            Place("Washington D.C.", "United States", "US", 38.9, -77.0, "America/New_York", resolved_from_country="United States"),
            "USA",
            "'USA' is a country; showing weather for its capital, Washington D.C.",
        ),
    ],
)
async def test_note_wording(place, requested, expected):
    respx.get(forecast.FORECAST_URL).respond(json={"daily": {"weather_code": [0]}})
    async with httpx.AsyncClient() as client:
        result = await forecast.daily_weather(client, place, date(2026, 11, 12), "metric", requested_location=requested)
    assert result.note == expected
