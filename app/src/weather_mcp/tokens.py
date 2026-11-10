import hmac
import json
import logging
import os
import time

log = logging.getLogger(__name__)

REFRESH_SECONDS = 300


class TokenStore:
    """Maps API tokens to consumer names.

    Source is the Secret Manager version named by TOKENS_SECRET
    (projects/<p>/secrets/<s>/versions/latest) holding {"consumer": "token", ...}. It is re-read every
    5 minutes so adding/revoking a consumer needs no redeploy. TOKENS_JSON overrides it for local runs.
    If no source is configured, the store is empty and every request is rejected.
    """

    def __init__(self, secret_version: str | None = None, static_json: str | None = None):
        self._secret_version = secret_version
        self._static_json = static_json
        self._by_consumer: dict[str, str] = {}
        self._loaded_at = float("-inf")
        self._client = None

    @classmethod
    def from_env(cls) -> "TokenStore":
        return cls(secret_version=os.environ.get("TOKENS_SECRET"), static_json=os.environ.get("TOKENS_JSON"))

    def _read_source(self) -> str:
        if self._static_json is not None:
            return self._static_json
        if self._secret_version:
            if self._client is None:
                from google.cloud import secretmanager

                self._client = secretmanager.SecretManagerServiceClient()
            return self._client.access_secret_version(name=self._secret_version).payload.data.decode()
        log.warning("No TOKENS_SECRET or TOKENS_JSON set; rejecting all requests")
        return "{}"

    def _refresh_if_stale(self) -> None:
        if time.monotonic() - self._loaded_at < REFRESH_SECONDS:
            return
        self._loaded_at = time.monotonic()
        try:
            parsed = json.loads(self._read_source())
            self._by_consumer = {str(k): str(v) for k, v in parsed.items()}
            log.info("Loaded %d consumer tokens", len(self._by_consumer))
        except Exception:
            # Keep the last good map on a transient failure rather than locking everyone out.
            log.exception("Failed to load consumer tokens")

    def consumer_for(self, token: str | None) -> str | None:
        if not token:
            return None
        self._refresh_if_stale()
        match = None
        for consumer, expected in self._by_consumer.items():
            # Compare against every entry so timing does not reveal which consumer matched.
            if hmac.compare_digest(token.encode(), expected.encode()):
                match = consumer
        return match
