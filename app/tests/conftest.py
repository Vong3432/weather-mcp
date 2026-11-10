import pytest

from weather_mcp import forecast, geocode


@pytest.fixture(autouse=True)
def clear_caches():
    geocode._cache._items.clear()
    forecast._cache._items.clear()
