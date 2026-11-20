"""Accounts, password checks, and signed session cookies.

Passwords are stored as scrypt hashes in a mounted users file. A session is a cookie holding the
username and an expiry, signed with HMAC-SHA256, so any replica can check it without shared
storage. The cost of that design: a single session cannot be revoked; rotating the session key
signs everyone out.
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
import time

from fastapi import Request
from starlette.responses import JSONResponse

from .passwords import DUMMY_HASH, b64, hash_password, unb64, verify_password  # noqa: F401

COOKIE = "assistant_session"
CLIENT_HEADER = "x-assistant-client"
class AuthConfigError(ValueError):
    """The users file or the session key is missing or malformed."""


@dataclass(frozen=True)
class User:
    username: str
    password_hash: str
    rate_limit_exempt: bool = False


def load_users(path: str) -> dict[str, User]:
    try:
        with open(path) as handle:
            entries = json.load(handle)["users"]
        users = {e["username"]: User(e["username"], e["passwordHash"], bool(e.get("rateLimitExempt", False)))
                 for e in entries}
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthConfigError("USERS_FILE must be JSON with a users list of username and passwordHash") from None
    if not users or any(not u.username or not u.password_hash.startswith("scrypt$") for u in users.values()):
        raise AuthConfigError("USERS_FILE must list at least one user, each with a scrypt passwordHash")
    return users


def load_key(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            key = handle.read().strip()
    except OSError:
        raise AuthConfigError("SESSION_KEY_FILE could not be read") from None
    if len(key) < 32:
        raise AuthConfigError("SESSION_KEY_FILE must hold at least 32 bytes")
    return key


class Sessions:
    def __init__(self, users: dict[str, User], key: bytes, lifetime_seconds: int, clock=time.time):
        self.users = users
        self.key = key
        self.lifetime = lifetime_seconds
        self.clock = clock

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.users.get(username)
        valid = verify_password(password, user.password_hash if user else DUMMY_HASH)
        return user if user and valid else None

    def issue(self, user: User) -> str:
        payload = b64(json.dumps({"u": user.username, "e": int(self.clock()) + self.lifetime}).encode())
        return f"{payload}.{self.sign(payload)}"

    def sign(self, payload: str) -> str:
        return b64(hmac.new(self.key, payload.encode(), hashlib.sha256).digest())

    def check(self, cookie: str | None) -> User | None:
        if not cookie or cookie.count(".") != 1:
            return None
        payload, signature = cookie.split(".")
        if not hmac.compare_digest(signature, self.sign(payload)):
            return None
        try:
            claims = json.loads(unb64(payload))
            username, expiry = claims["u"], int(claims["e"])
        except (ValueError, KeyError, TypeError):
            return None
        if expiry <= self.clock():
            return None
        # A user removed from the users file loses access at their next request.
        return self.users.get(username)


def current_user(request: Request) -> User | None:
    return request.app.state.sessions.check(request.cookies.get(COOKIE))


def forbidden_mutation(request: Request) -> JSONResponse | None:
    """State-changing requests need the expected Origin and the custom header, on top of
    SameSite=Strict. A cross-site form or script cannot send that header without a preflight
    the server never approves."""
    settings = request.app.state.settings
    if request.headers.get("origin") != settings.allowed_origin or request.headers.get(CLIENT_HEADER) != "1":
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return None


def unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


def client_address(request: Request, forwarded_hops: int) -> str:
    """The caller's address. Behind GKE's external Application Load Balancer, the verified client
    address is the second-to-last X-Forwarded-For entry, so forwarded_hops is 2 there and 0 locally."""
    if forwarded_hops:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= forwarded_hops:
            return hops[-forwarded_hops]
    return request.client.host if request.client else "unknown"
