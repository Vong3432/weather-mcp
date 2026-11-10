# Deploy Guide

This guide covers deploying the Weather MCP server to **Google Cloud Run**, giving consumers access, and operating it. For local development, see the [Setup guide](SETUP.md).

## Overview

`deploy.sh` creates or updates everything below in the Google Cloud project and region set in `.env` (default region `asia-southeast1`, Singapore). It's safe to re-run.

| Resource | Name | Purpose |
|---|---|---|
| Cloud Run service | `weather-mcp` | Runs the server. Public, scales 0 → 2 instances, 1 vCPU / 512 MiB. |
| Secret Manager secret | `weather-mcp-tokens` | Holds the `{"consumer": "token"}` map. |
| Service account | `weather-mcp-run` | Runtime identity. Can only read the token secret. |
| Service account | `weather-mcp-build` | Cloud Build identity for source deploys. Has only **Cloud Run Builder** (`roles/run.builder`). |
| Logging exclusion | `weather-mcp-request-urls` | Keeps Cloud Run request logs, which would contain `/mcp/<token>` URLs, out of Cloud Logging. |
| Artifact Registry repo | `cloud-run-source-deploy` | Created automatically by `gcloud run deploy --source` to store the image. |

The service URL looks like `https://weather-mcp-<hash>-as.a.run.app`. It stays the same across redeploys as long as the service isn't deleted.

## 1. Prerequisites

1. **A Google Cloud account** with a **billing account**. Billing must be enabled even though normal usage stays in the free tier.
2. **The Google Cloud CLI:**

   ```sh
   brew install --cask google-cloud-sdk
   gcloud auth login
   ```

3. **Python 3** (any recent version) to run the token scripts. They have no extra dependencies, so plain `python3` is enough and uv isn't needed.
4. **uv** *(optional)*: only needed to run the test suite before redeploying (step 6). Install it with `brew install uv`; see the [Setup guide](SETUP.md#1-prerequisites).

Docker isn't needed: Cloud Build builds the image in the cloud, using the uv version pinned in `app/Dockerfile` and the dependencies locked in `app/uv.lock`.

## 2. Configure the project

### Save the project ID in `.env`

`deploy.sh` and the token scripts read their settings from a `.env` file in the repository root. Create it from the template:

```sh
cp .env.example .env
```

Then edit `.env`:

```sh
PROJECT_ID=my-weather-mcp     # your Google Cloud project id (required)
REGION=asia-southeast1        # Cloud Run region (optional, this is the default)
```

Project IDs are globally unique, so choose your own in place of `my-weather-mcp`. If you already have a project, use its ID.

`.env` is git-ignored, so it stays local. A variable set in your shell overrides `.env` for one run, e.g. `PROJECT_ID=other-project ./deploy.sh`.

The plain `gcloud` commands in this guide use `$PROJECT_ID` and `$REGION`. Load `.env` into your shell once per terminal session:

```sh
set -a; source .env; set +a
```

### Create the project

Skip this if the project already exists.

```sh
gcloud projects create "$PROJECT_ID" --name="Weather MCP"
gcloud billing accounts list                          # find your billing account ID
gcloud billing projects link "$PROJECT_ID" --billing-account=XXXXXX-XXXXXX-XXXXXX
```

Your account needs roles that let it enable APIs and manage Cloud Run, Secret Manager, IAM service accounts, Cloud Build and Logging. **Owner** on the project covers all of these.

## 3. Deploy

From the repository root:

```sh
./deploy.sh
```

It reads `PROJECT_ID` and `REGION` from `.env`. To use a different region, change `REGION` there. The token scripts read the same file, so they stay in sync.

The first run takes about 3–5 minutes (it enables APIs and builds the image). It ends with:

```
Deployed: https://weather-mcp-xxxxxxxxxx-as.a.run.app
Health:   {"status":"ok"}
Next:     python3 scripts/add_token.py <consumer-name>
```

## 4. Verify

```sh
URL=$(gcloud run services describe weather-mcp --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')

curl "$URL/health"                                    # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/mcp"   # 401: auth is enforced
```

## 5. Add consumers

Each consumer (a person, team or ChatGPT workspace) gets its own token:

```sh
python3 scripts/add_token.py alice
```

This prints:

- the **token**, shown only once,
- a ready-to-paste **VS Code `.vscode/mcp.json`** snippet. It doesn't contain the token: VS Code prompts for it and sends it as a Bearer header ([VS Code setup](SETUP.md#vs-code-github-copilot)).
- the **ChatGPT connector URL**, `https://…/mcp/<token>`.

Send these to the consumer over a private channel. The new token works **within 5 minutes**, with no redeploy. Client setup steps are in the [Setup guide](SETUP.md#6-connect-a-client).

### Revoke or list consumers

```sh
python3 scripts/revoke_token.py --list
python3 scripts/revoke_token.py alice
```

A revoked token stops working within 5 minutes. To **rotate** a token, revoke it and add the consumer again.

Each change writes a new secret version and destroys the old ones, so revoked tokens don't linger in older versions.

## 6. Redeploy after code changes

```sh
cd app && uv run pytest && cd ..
./deploy.sh
```

Cloud Run moves traffic to the new revision only once it starts successfully. To roll back:

```sh
gcloud run revisions list --service weather-mcp --project "$PROJECT_ID" --region "$REGION"
gcloud run services update-traffic weather-mcp --project "$PROJECT_ID" --region "$REGION" \
  --to-revisions=<previous-revision>=100
```

## 7. Monitor

**Application logs.** These show each call's consumer, location and date, but never the token.

```sh
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="weather-mcp"' \
  --project "$PROJECT_ID" --limit 50 --format='value(timestamp, textPayload)'
```

Or open **Cloud Console → Cloud Run → weather-mcp → Logs**. The **Metrics** tab shows request count, latency and instance count.

Request logs are excluded on purpose (see Overview), so the URLs Cloud Run would log are not there.

## 8. Cost

At low traffic this should cost **about $0 a month**:

| Item | Free tier | Notes |
|---|---|---|
| Cloud Run | 2M requests, 180k vCPU-seconds, 360k GiB-seconds a month | Request-based billing; nothing is charged while idle. |
| Cloud Build | 2,500 build-minutes a month | About 1–2 minutes per deploy. |
| Artifact Registry | 0.5 GB of storage | Delete old images if they pile up. |
| Secret Manager | 6 active versions, 10k access operations a month | The scripts keep a single active version. |
| Cloud Logging | 50 GiB a month | |

To catch surprises, set a budget alert under **Billing → Budgets & alerts** (e.g. $5).

**Limits that cap cost and load:** at most 2 instances, 40 concurrent requests per instance, and an in-app rate limit of 10 requests/s with a burst of 20 per instance. Change these in `deploy.sh` (`--max-instances`, `--concurrency`) and `app/src/weather_mcp/auth.py` (`RateLimiter`).

**Cold starts:** with `--min-instances=0`, the first request after a quiet period takes about 1–2 s. Setting `--min-instances=1` removes cold starts but costs roughly $10+ a month.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `deploy.sh` fails with `PERMISSION_DENIED` | Your account lacks a role in the project. Use Owner, or ask the admin for Cloud Run Admin, Secret Manager Admin, Service Account Admin, Cloud Build Editor and Logging Config Writer. |
| `--allow-unauthenticated` fails with an org policy error | Your organisation enforces *Domain restricted sharing*, which blocks public (`allUsers`) access. Ask an org admin for an exception for this project, or use a project outside the organisation. |
| Billing error during `services enable` | Link a billing account to the project (step 2). |
| New token returns `401` | It can take up to 5 minutes to propagate. Check the consumer exists with `revoke_token.py --list`. |
| `Set PROJECT_ID in .env …` | `.env` is missing or has no `PROJECT_ID`. Run `cp .env.example .env` in the repo root and set it (step 2). |
| `gcloud` commands fail with an empty `--project` or `--region` | `.env` isn't loaded in this terminal. Run `set -a; source .env; set +a`. |
| `PERMISSION_DENIED: Build failed because the default service account is missing required IAM permissions` | Builds were running as the Compute Engine default service account, which newer projects don't grant build permissions to. `deploy.sh` now uses a dedicated `weather-mcp-build` account; re-run it. If it fails right after the account is created, wait a minute for IAM to propagate and run it again. |
| Every request returns `401` | Check that the runtime can read the secret: logs show `Failed to load consumer tokens`. Re-run `deploy.sh` to restore the IAM binding. |
| Requests return `429` | The in-app rate limit was hit. Raise `RateLimiter` limits if the traffic is legitimate. |
| ChatGPT says the connector is unreachable or failed | Check that the URL ends in `/mcp/<token>`, authentication is **No authentication**, and Developer mode is on. Try again after a cold start. |
| Tool says "weather service is temporarily unavailable" | Open-Meteo returned an error or timed out (10 s). This is usually transient. Check [status.open-meteo.com](https://status.open-meteo.com). |

## 10. Tear down

Run these to delete everything `deploy.sh` created:

```sh
set -a; source .env; set +a
gcloud run services delete weather-mcp --project "$PROJECT_ID" --region "$REGION"
gcloud secrets delete weather-mcp-tokens --project "$PROJECT_ID"
gcloud iam service-accounts delete "weather-mcp-run@$PROJECT_ID.iam.gserviceaccount.com" --project "$PROJECT_ID"
gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:weather-mcp-build@$PROJECT_ID.iam.gserviceaccount.com" --role=roles/run.builder
gcloud iam service-accounts delete "weather-mcp-build@$PROJECT_ID.iam.gserviceaccount.com" --project "$PROJECT_ID"
gcloud logging sinks update _Default --remove-exclusions=weather-mcp-request-urls --project "$PROJECT_ID"
gcloud artifacts repositories delete cloud-run-source-deploy --location "$REGION" --project "$PROJECT_ID"
```

Or delete the whole project: `gcloud projects delete "$PROJECT_ID"`.

**Deleting the service changes the URL.** Every consumer will need a new connection URL after a redeploy.
