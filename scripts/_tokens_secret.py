"""Shared helpers for the token scripts: read/write the consumer→token map in Secret Manager via gcloud."""

import json
import os
import subprocess
import sys
from pathlib import Path

SECRET = "weather-mcp-tokens"
SERVICE = "weather-mcp"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file() -> None:
    """Load KEY=VALUE lines from the repo's .env without overriding variables already set in the shell."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env_file()


def project() -> str:
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        sys.exit("Set PROJECT_ID in .env (copy .env.example) or in the environment.")
    return project_id


def region() -> str:
    return os.environ.get("REGION", "asia-southeast1")


def gcloud(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["gcloud", "--project", project(), "--quiet", *args], input=stdin, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(result.stderr.strip())
    return result.stdout.strip()


def read_tokens() -> dict[str, str]:
    return json.loads(gcloud("secrets", "versions", "access", "latest", f"--secret={SECRET}") or "{}")


def write_tokens(tokens: dict[str, str]) -> None:
    gcloud("secrets", "versions", "add", SECRET, "--data-file=-", stdin=json.dumps(tokens, indent=1, sort_keys=True))
    # Destroy superseded versions: old maps still hold revoked tokens, and Secret Manager bills per active version.
    versions = gcloud("secrets", "versions", "list", SECRET, "--filter=state=ENABLED", "--format=value(name.basename())").split()
    for version in sorted(versions, key=int)[:-1]:
        gcloud("secrets", "versions", "destroy", version, f"--secret={SECRET}")


def service_url() -> str:
    return gcloud("run", "services", "describe", SERVICE, f"--region={region()}", "--format=value(status.url)")
