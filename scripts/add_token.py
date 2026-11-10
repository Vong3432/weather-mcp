"""Create an API token for a consumer and print how to connect.

Usage: python3 scripts/add_token.py <consumer-name>
Reads PROJECT_ID and REGION from .env (see .env.example).
"""

import json
import secrets
import sys

from _tokens_secret import read_tokens, service_url, write_tokens


def main(consumer: str) -> None:
    tokens = read_tokens()
    if consumer in tokens:
        sys.exit(f"'{consumer}' already has a token. Revoke it first to rotate.")
    token = "wmcp_" + secrets.token_urlsafe(32)
    tokens[consumer] = token
    write_tokens(tokens)

    url = service_url()
    vscode = {
        "inputs": [
            {
                "type": "promptString",
                "id": "weather-token",
                "description": "Weather MCP API token (from scripts/add_token.py)",
                "password": True,
            }
        ],
        "servers": {
            "weather": {"type": "http", "url": f"{url}/mcp", "headers": {"Authorization": "Bearer ${input:weather-token}"}}
        },
    }
    print(f"Token for '{consumer}' (shown once, active within 5 minutes):\n\n  {token}\n")
    print("VS Code — .vscode/mcp.json (VS Code prompts for the token once and stores it securely):\n")
    print(json.dumps(vscode, indent=2))
    print("\nChatGPT (Developer mode) — add a custom connector, Authentication: No authentication, URL (keep secret):\n")
    print(f"  {url}/mcp/{token}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
