import httpx
import pytest
import respx

from weather_mcp import geocode


def _result(name, country, code, tz):
    return {"results": [{"name": name, "country": country, "country_code": code, "latitude": 1.0, "longitude": 2.0, "timezone": tz}]}


@respx.mock
@pytest.mark.parametrize("query", ["Japan", "japan", "  Nippon "])
async def test_country_resolves_to_capital(query):
    route = respx.get(geocode.GEOCODING_URL).respond(json=_result("Tokyo", "Japan", "JP", "Asia/Tokyo"))
    async with httpx.AsyncClient() as client:
        place = await geocode.resolve(client, query)

    params = route.calls.last.request.url.params
    assert params["name"] == "Tokyo"
    assert params["countryCode"] == "JP"
    assert place.resolved_from_country == "Japan"
    assert place.label == "Tokyo, Japan"


@respx.mock
async def test_dotted_alias_matches():
    route = respx.get(geocode.GEOCODING_URL).respond(json=_result("Washington", "United States", "US", "America/New_York"))
    async with httpx.AsyncClient() as client:
        place = await geocode.resolve(client, "U.S.A.")
    assert route.calls.last.request.url.params["countryCode"] == "US"
    assert place.resolved_from_country == "United States"


@respx.mock
async def test_city_is_searched_directly():
    route = respx.get(geocode.GEOCODING_URL).respond(json=_result("Paris", "France", "FR", "Europe/Paris"))
    async with httpx.AsyncClient() as client:
        place = await geocode.resolve(client, "Paris")
    assert "countryCode" not in route.calls.last.request.url.params
    assert place.resolved_from_country is None


@respx.mock
async def test_results_are_cached():
    route = respx.get(geocode.GEOCODING_URL).respond(json=_result("Paris", "France", "FR", "Europe/Paris"))
    async with httpx.AsyncClient() as client:
        await geocode.resolve(client, "Paris")
        await geocode.resolve(client, "paris")
    assert route.call_count == 1


@respx.mock
async def test_unknown_place():
    respx.get(geocode.GEOCODING_URL).respond(json={})
    async with httpx.AsyncClient() as client:
        with pytest.raises(geocode.LocationNotFound, match="Qwxzzy"):
            await geocode.resolve(client, "Qwxzzy")
