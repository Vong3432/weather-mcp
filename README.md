# Weather MCP

A small remote [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for checking the weather from an AI assistant. Users ask in plain language, for example *"What's the weather in Japan tomorrow?"*, from **VS Code (GitHub Copilot)** or **ChatGPT**. The assistant calls this server and gets the forecast back.

It runs on **Google Cloud Run** at a permanent public HTTPS URL. Weather data comes from [Open-Meteo](https://open-meteo.com), which is free and needs no API key.

## Features

- **One tool: `get_weather(location, date, units)`.** Returns the daily forecast: condition, min/max temperature, precipitation amount and probability, and max wind speed.
- **Any place name.** Cities, regions and countries all work. A country resolves to its capital, and the response says so ("Japan" → Tokyo).
- **Today and future dates only.** Supports today up to 15 days ahead, using the **location's local date**. Past dates and dates too far ahead are rejected with the allowed range.
- **Asks for missing dates.** If the user doesn't give a date, the assistant is told to ask for one instead of assuming today.
- **Metric or imperial units** (°C/mm/km/h or °F/in/mph).
- **Per-consumer API tokens.** Each consumer gets its own token, and revoking one doesn't affect the others.
- **Close to zero cost.** It scales to zero when idle and fits within Google Cloud's free tiers at low traffic.

## How it works

```
 VS Code (Copilot)  ──  Authorization: Bearer <token>  ──┐
                                                          ├──►  Cloud Run: weather-mcp  ──►  Open-Meteo
 ChatGPT connector  ──  https://…/mcp/<token>  ──────────┘      (Python, MCP over            (geocoding +
                                                                 Streamable HTTP)              forecast)
                                                                      │
                                                                      └──►  Secret Manager
                                                                            (consumer → token map)
```

- **Transport:** stateless Streamable HTTP with JSON responses, at `/mcp`. Any instance can serve any request.
- **Auth:** VS Code sends the token as a Bearer header. ChatGPT custom connectors only support no auth or OAuth, so ChatGPT consumers put the token in the URL path instead. Request paths are never logged.
- **Token store:** a JSON map in Secret Manager, re-read every 5 minutes, so adding or revoking a consumer needs no redeploy.
- **Protection:** a global rate limit (10 requests/s, burst of 20, per instance) and at most 2 instances. Together these protect Open-Meteo's free quota.
- **Caching:** forecasts are cached in memory for 30 minutes and geocoding results for 30 days.

## Project structure

```
weather-mcp/
├── app/                          # The MCP server (Python 3.12, uv)
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/weather_mcp/
│   │   ├── server.py             # MCP server, get_weather tool, /health, app entrypoint
│   │   ├── auth.py               # Token check (header or path) and global rate limiter
│   │   ├── tokens.py             # Loads the consumer → token map from Secret Manager
│   │   ├── geocode.py            # Place lookup; country → capital
│   │   ├── forecast.py           # Date validation and Open-Meteo forecast call
│   │   ├── wmo_codes.py          # Weather code → text ("Slight rain")
│   │   ├── cache.py              # In-memory TTL cache
│   │   └── data/countries.json   # Country names/aliases → capital
│   └── tests/                    # pytest (Open-Meteo mocked)
├── scripts/
│   ├── add_token.py              # Create a consumer token; prints VS Code / ChatGPT setup
│   ├── revoke_token.py           # Revoke or list consumers
│   └── build_countries.py        # Regenerate countries.json
├── deploy.sh                     # Deploy to Google Cloud Run (safe to re-run)
├── .github/agents/weather.agent.md  # Copilot custom agent that uses this MCP server
├── .env.example                  # Template for .env (PROJECT_ID, REGION), read by deploy.sh and scripts
└── docs/
    ├── SETUP.md                  # Local development and connecting clients
    └── DEPLOY.md                 # Deploying and operating on Google Cloud
```

## Documentation

- **[Setup guide](docs/SETUP.md):** install, run and test locally, then connect VS Code or ChatGPT.
  - [Connect VS Code (GitHub Copilot)](docs/SETUP.md#vs-code-github-copilot): step by step, with the token entered at a prompt. Includes the ready-made **Weather** Copilot agent.
- **[Deploy guide](docs/DEPLOY.md):** deploy to Google Cloud Run, manage consumer tokens, monitor, troubleshoot and tear down.

## Example

> **User:** What's the weather in Japan tomorrow?
>
> **Assistant** *(calls `get_weather("Japan", "2026-11-11")`)*: Tomorrow in Tokyo (Japan's capital) will be clear, with temperatures between 6 °C and 14 °C, no rain expected, and light winds up to about 5 km/h.

## Limitations

- **Forecasts only.** Historical weather is out of scope.
- **One location per call**, and a country is represented by its capital rather than the whole country.
- **Open-Meteo's free API is for non-commercial use only** (about 10,000 calls a day). Commercial use needs an [Open-Meteo plan](https://open-meteo.com/en/pricing).
