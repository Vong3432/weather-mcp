"""Revoke a consumer's API token. Takes effect within 5 minutes.

Usage: python3 scripts/revoke_token.py <consumer-name>
       python3 scripts/revoke_token.py --list
Reads PROJECT_ID and REGION from .env (see .env.example).
"""

import sys

from _tokens_secret import read_tokens, write_tokens


def main(arg: str) -> None:
    tokens = read_tokens()
    if arg == "--list":
        print("\n".join(sorted(tokens)) or "(no consumers)")
        return
    if tokens.pop(arg, None) is None:
        sys.exit(f"No consumer named '{arg}'.")
    write_tokens(tokens)
    print(f"Revoked '{arg}'.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
