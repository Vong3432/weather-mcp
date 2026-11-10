"""Regenerate app/src/weather_mcp/data/countries.json from the mledoze/countries dataset.

Usage: python scripts/build_countries.py <path-to-mledoze-countries.json>
Source: https://cdn.jsdelivr.net/gh/mledoze/countries@master/countries.json (ODbL)
"""

import json
import sys
from pathlib import Path

# Two-letter alt spellings are mostly ISO codes that collide with place names ("LA", "PA"); keep only these.
KEEP_SHORT_ALIASES = {"UK", "US"}

# Capitals whose dataset spelling Open-Meteo's geocoder does not find (checked against countryCode).
GEOCODE_AS = {
    "GG": "Saint Peter Port",
    "HK": "Hong Kong",
    "KI": "Tarawa",
    "SM": "San Marino",
    "TK": "Atafu",
    "EH": "Laayoune",
}
# No geocodable capital at all; these fall through to a normal place-name search.
SKIP = {"IO"}

OUT = Path(__file__).resolve().parent.parent / "app/src/weather_mcp/data/countries.json"


def main(src: str) -> None:
    countries = []
    for c in json.loads(Path(src).read_text()):
        if not c.get("capital") or c["cca2"] in SKIP:
            continue
        aliases = {c["name"]["common"], c["name"]["official"]}
        aliases.update(a for a in c.get("altSpellings", []) if len(a) > 2 or a in KEEP_SHORT_ALIASES)
        countries.append(
            {
                "code": c["cca2"],
                "name": c["name"]["common"],
                "capital": GEOCODE_AS.get(c["cca2"], c["capital"][0]),
                "aliases": sorted(aliases),
            }
        )
    countries.sort(key=lambda c: c["name"])
    OUT.write_text(json.dumps(countries, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(countries)} countries to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
