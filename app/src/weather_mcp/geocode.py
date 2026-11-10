import json
from dataclasses import dataclass
from importlib import resources

import httpx

from weather_mcp.cache import TTLCache

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class LocationNotFound(Exception):
    pass


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    country_code: str
    latitude: float
    longitude: float
    timezone: str
    admin1: str | None = None
    resolved_from_country: str | None = None  # set when the user asked for a country and we used its capital

    @property
    def label(self) -> str:
        parts: list[str] = []
        for part in (self.name, self.admin1, self.country):
            if part and part not in parts:
                parts.append(part)
        return ", ".join(parts)


def _load_countries() -> dict[str, dict]:
    raw = json.loads(resources.files("weather_mcp").joinpath("data/countries.json").read_text())
    by_alias: dict[str, dict] = {}
    for country in raw:
        for alias in country["aliases"]:
            by_alias.setdefault(_normalise(alias), country)
    return by_alias


def _normalise(text: str) -> str:
    return " ".join(text.casefold().replace(".", "").split())


_COUNTRIES = _load_countries()
_cache = TTLCache(ttl_seconds=30 * 24 * 3600)


async def resolve(client: httpx.AsyncClient, location: str) -> Place:
    """Turn free text into a single place. A bare country name resolves to its capital."""
    location = location.strip()
    if not location:
        raise LocationNotFound("Location is empty.")

    country = _COUNTRIES.get(_normalise(location))
    if country:
        place = await _search(client, country["capital"], country_code=country["code"])
        if place is None:
            raise LocationNotFound(f"Could not locate {country['capital']}, the capital of {country['name']}.")
        return Place(**{**place.__dict__, "resolved_from_country": country["name"]})

    place = await _search(client, location)
    if place is None:
        raise LocationNotFound(f"Could not find a place called '{location}'. Try a city name.")
    return place


async def _search(client: httpx.AsyncClient, name: str, country_code: str | None = None) -> Place | None:
    key = (_normalise(name), country_code)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    params = {"name": name, "count": 1, "language": "en", "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    resp = await client.get(GEOCODING_URL, params=params)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return None
    r = results[0]
    place = Place(
        name=r["name"],
        country=r.get("country", ""),
        country_code=r.get("country_code", ""),
        latitude=r["latitude"],
        longitude=r["longitude"],
        timezone=r.get("timezone") or "UTC",
        admin1=r.get("admin1"),
    )
    _cache.set(key, place)
    return place
