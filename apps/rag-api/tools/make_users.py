#!/usr/bin/env python3
"""Prints a users file for rag-api: each account's username and scrypt password hash.

Prompts go to the terminal and the JSON goes to standard output, so you can pipe it straight
into Secret Manager without the passwords appearing anywhere:

    apps/rag-api/tools/make_users.py | gcloud secrets versions add staging-rag-api-users --data-file=-

Mark the load generator's account as rate-limit exempt when prompted; it still counts against
the admission limit.
"""

import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rag_api.auth import hash_password  # noqa: E402


def ask(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def main() -> int:
    users = []
    while True:
        username = ask("Username (empty to finish): ")
        if not username:
            break
        password = getpass.getpass("Password: ", stream=sys.stderr)
        if len(password) < 12 or password != getpass.getpass("Again: ", stream=sys.stderr):
            print("Passwords must match and be at least 12 characters.", file=sys.stderr)
            continue
        exempt = ask("Exempt from the rate limit, for the load generator? [y/N]: ").lower() == "y"
        users.append({"username": username, "passwordHash": hash_password(password), "rateLimitExempt": exempt})
    if not users:
        print("No users entered.", file=sys.stderr)
        return 1
    json.dump({"users": users}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
