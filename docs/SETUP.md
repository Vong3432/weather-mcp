# Setup Guide

This guide covers running the Weather MCP server on your own machine, testing it, and connecting VS Code or ChatGPT to it. To put it on the internet, see the [Deploy guide](DEPLOY.md).

## 1. Prerequisites

| Tool | Version | Install (macOS) |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) (Python package manager) | 0.13 or newer | `brew install uv` |
| Python | 3.12 or newer | Optional: uv downloads a suitable Python automatically if none is installed |
| Node.js *(optional, for MCP Inspector)* | 18 or newer | `brew install node` |
| Docker *(optional, to test the container)* | any | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |

Without Homebrew, install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh` and open a new terminal so it's on your `PATH`. Then check it:

```sh
uv --version
# uv 0.13.7 (or newer)
```

No weather API key is needed, because Open-Meteo is free and keyless.

## 2. Install dependencies

```sh
cd app
uv sync
```

This creates `app/.venv` with the server and its test dependencies, pinned by `app/uv.lock`. Commit `uv.lock` whenever dependencies change: the Docker build installs from it with `uv sync --locked` and fails if it's out of date.

To add or upgrade a dependency:

```sh
cd app
uv add <package>          # runtime dependency
uv add --dev <package>    # test-only dependency
uv lock --upgrade         # upgrade everything within pyproject.toml constraints
```

## 3. Run the tests

```sh
cd app
uv run pytest
```

The tests mock Open-Meteo, so they need no network access. They cover date validation (including time-zone edge cases), country → capital lookup, token auth on the header and path forms, and rate limiting.

## 4. Run the server locally

Locally, tokens come from the `TOKENS_JSON` environment variable instead of Secret Manager:

```sh
cd app
TOKENS_JSON='{"dev": "tok_dev"}' PORT=8000 uv run weather-mcp
```

Check that it's up:

```sh
curl http://localhost:8000/health
# {"status":"ok"}
```

Call the tool directly, using the path-token form:

```sh
curl -s -X POST http://localhost:8000/mcp/tok_dev \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_weather","arguments":{"location":"Japan","date":"2026-11-11"}}}'
```

Replace the date with one between today and 15 days from now. Past dates are rejected by design.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | Port to listen on | `8080` |
| `TOKENS_JSON` | Inline `{"consumer": "token"}` map, for local use | unset |
| `TOKENS_SECRET` | Secret Manager version to read tokens from (set by `deploy.sh`) | unset |

If neither `TOKENS_JSON` nor `TOKENS_SECRET` is set, every request is rejected with `401`.

### Run it in Docker (optional)

This is the same image Cloud Run uses. It has its own pinned copy of uv (see `app/Dockerfile`), so a local uv install isn't involved:

```sh
cd app
docker build -t weather-mcp .
docker run --rm -p 8000:8080 -e TOKENS_JSON='{"dev":"tok_dev"}' weather-mcp
```

## 5. Explore with MCP Inspector (optional)

```sh
npx @modelcontextprotocol/inspector
```

In the Inspector UI, choose transport **Streamable HTTP** and enter the URL `http://localhost:8000/mcp/tok_dev`. Click **Connect**, open **Tools** and run `get_weather`.

## 6. Connect a client

### VS Code (GitHub Copilot)

VS Code sends the token as an `Authorization: Bearer` header. The config below **prompts you for the token** the first time the server starts and keeps it in VS Code's encrypted secret storage, so `mcp.json` itself never contains a secret.

**Requirements:** VS Code 1.102 or newer with the GitHub Copilot extension, signed in.

#### Step 1: Get a token and the server URL

Ask the operator for a token, or create one yourself if you have access to the Google Cloud project (see the [Deploy guide](DEPLOY.md#5-add-consumers)):

```sh
python3 scripts/add_token.py vscode-<your-name>
```

Run it in your own terminal. The token (`wmcp_…`) is shown **only once**, and it works within about 5 minutes. The script also prints the service URL and a ready-made `mcp.json`.

To look up the service URL later:

```sh
set -a; source .env; set +a
gcloud run services describe weather-mcp --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)'
```

#### Step 2: Add the server configuration

Create `.vscode/mcp.json` in your workspace and replace `<service-url>` with the URL from step 1:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "weather-token",
      "description": "Weather MCP API token (from scripts/add_token.py)",
      "password": true
    }
  ],
  "servers": {
    "weather": {
      "type": "http",
      "url": "https://<service-url>/mcp",
      "headers": {
        "Authorization": "Bearer ${input:weather-token}"
      }
    }
  }
}
```

- The `url` ends in `/mcp`, with **no token in it**. The token goes only in the header.
- `"password": true` masks the token as you type it.
- You can also create this file with **MCP: Add Server** → **HTTP** from the Command Palette, then add the `inputs` and `headers` blocks.

#### Step 3: Start the server and enter the token

1. Open `.vscode/mcp.json`. Above `"weather"`, click **Start**, or run **MCP: List Servers** → `weather` → **Start Server**.
2. When VS Code asks for *"Weather MCP API token"*, paste the `wmcp_…` token and press Enter.
3. The status above `"weather"` changes to **Running** and shows **1 tool** (`get_weather`).

VS Code remembers the token for this workspace and doesn't ask again.

#### Step 4: Use it in Copilot Chat

1. Open Copilot Chat and switch the mode dropdown to **Agent**. Tools are only used in Agent mode.
2. Optionally, click the **tools** icon to check that **weather → get_weather** is enabled.
3. Ask, for example:
   - *"What's the weather in Japan tomorrow?"* uses Tokyo, Japan's capital.
   - *"Will it rain in Kuala Lumpur on Saturday? Use imperial units."*
   - *"What's the weather in Paris?"* Copilot should **ask you which date**, because the tool never assumes today.
4. The first time, Copilot asks permission to run `get_weather`. Choose **Allow** (once, for the session, or always).

#### Step 5 (optional): Use the Weather agent

The repo includes a Copilot custom agent, `.github/agents/weather.agent.md`. It has access only to this MCP server's tools and is told to:
- ask for a date when you don't give one,
- respect the today-to-15-days limit,
- answer with the resolved place and date, a one-line summary, and a table when you compare several places or days.

1. Make sure the `weather` server is running (step 3).
2. In Copilot Chat, open the agent dropdown (where it says **Agent**) and choose **Weather**.
3. Ask, for example: *"Compare Tokyo and Seoul tomorrow"* or *"What's the weekend looking like in Paris?"*

To change its behaviour, edit the instructions in the agent file. The `tools: ['weather/*']` line must match the server name in `mcp.json` (`"weather"`). If you rename the server, update this line too.

#### Change or rotate the token

To enter a different token, for example after the operator revokes the old one:

1. Run **MCP: List Servers** → `weather` → **Stop Server**.
2. Clear the saved value. Run **MCP: Reset Cached Tools**, or open `mcp.json`, hover over the `inputs` entry, and choose **Edit** or **Clear** on the stored `weather-token` value.
3. Start the server again. VS Code prompts for the new token.

#### Use it in every workspace (optional)

`.vscode/mcp.json` only applies to the folder it's in. To have the weather tool in all your projects, run **MCP: Open User Configuration** and paste the same `inputs` and `servers` blocks there instead.

#### Point VS Code at a local server

When running the server locally (step 4 of this guide), use `"url": "http://localhost:8000/mcp"` and enter the token from your `TOKENS_JSON`, for example `tok_dev`.

### ChatGPT

ChatGPT connects from OpenAI's servers, so it **can't reach `localhost`**. Deploy first (see the [Deploy guide](DEPLOY.md)), or expose your local server with a tunnel such as `cloudflared tunnel --url http://localhost:8000`.

1. You need a ChatGPT plan that supports **Developer mode** (Plus, Pro, Business or Enterprise). On workspace plans an admin may have to enable it.
2. In ChatGPT, open **Settings → Apps & Connectors → Advanced settings** and turn on **Developer mode**.
3. Create a new connector:
   - **Name:** Weather
   - **MCP Server URL:** `https://<service-url>/mcp/<your-token>`
   - **Authentication:** No authentication
4. In a new chat, enable the Weather connector from the tools menu and ask: *"Will it rain in Kuala Lumpur this Saturday?"*

ChatGPT can't send custom headers, so the token goes in the URL. **Treat the whole URL as a password**: don't paste it into shared chats or documents.

## 7. Updating the country list (rarely needed)

`app/src/weather_mcp/data/countries.json` maps country names and aliases to capitals. To regenerate it from the [mledoze/countries](https://github.com/mledoze/countries) dataset:

```sh
curl -sSL -o /tmp/countries.json https://cdn.jsdelivr.net/gh/mledoze/countries@master/countries.json
python3 scripts/build_countries.py /tmp/countries.json
```

The script has a small override table (`GEOCODE_AS`) for capitals whose spelling Open-Meteo's geocoder doesn't recognise.

## 8. Keeping secrets out of git

This repository is public. Real tokens and project settings must never be committed:

- `.env` (your `PROJECT_ID`) and credential files (`*.pem`, `*service-account*.json`, `credentials*.json`, …) are git-ignored. Only `.env.example` is tracked.
- Consumer tokens live only in Secret Manager. `scripts/add_token.py` prints them to your terminal once; don't paste them into files in the repo.
- Tokens start with `wmcp_`, which makes them easy to spot if one does leak.
- `.github/workflows/secret-scan.yml` runs [gitleaks](https://github.com/gitleaks/gitleaks) on every push and pull request.

Scan your staged changes before committing:

```sh
brew install gitleaks
gitleaks git --staged --no-banner .
```

If a token is ever committed, **revoke it first** with `python3 scripts/revoke_token.py <consumer>`, then remove it from the history. Deleting it in a later commit isn't enough, because the old commit stays public.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `uv: command not found` | uv isn't installed or isn't on your `PATH`. Run `brew install uv`; if you used the curl installer, open a new terminal. |
| Docker build fails at `uv sync --locked` | `uv.lock` is out of date with `pyproject.toml`. Run `uv lock` in `app/` and commit the result. |
| `401 {"error":"invalid_token"}` | Wrong or missing token. Check `TOKENS_JSON` and the header or URL. |
| VS Code: server fails to start, output shows `401` | The token is wrong, revoked, or less than 5 minutes old. Wait a few minutes, or clear the stored token and start again (see *Change or rotate the token*). |
| VS Code: server is **Running** but Copilot never calls the tool | Copilot Chat isn't in **Agent** mode, or `get_weather` is unticked in the tools picker. |
| VS Code: the token prompt never appears | VS Code already has a stored value for `weather-token`. Clear it (see *Change or rotate the token*). |
| VS Code: **Weather** missing from the agent dropdown | The agent file must be at `.github/agents/weather.agent.md` in the folder you opened. Reload the window (**Developer: Reload Window**). |
| VS Code: Weather agent says it has no weather tool | The `weather` MCP server isn't running, or its name in `mcp.json` doesn't match `weather/*` in the agent file. |
| VS Code: first request is slow or times out | Cold start: the service scales to zero when idle. The first call takes about 1–2 s; retry once. |
| `406` or `Invalid Content-Type header` | A raw HTTP call is missing `content-type: application/json` and `accept: application/json, text/event-stream`. |
| `429 {"error":"rate_limited"}` | More than about 20 requests in a burst. Wait a second and retry. |
| Tool error "outside the supported range" | The date is in the past or more than 15 days ahead in the location's local time. |
| Tool error "Could not find a place" | Open-Meteo's geocoder doesn't know the name. Try a nearby city. |
