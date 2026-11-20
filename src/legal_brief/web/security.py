"""Password hashing (scrypt) and signed session tokens (HMAC-SHA256), standard library only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

SESSION_COOKIE = "lb_session"
SESSION_DAYS = 14
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def secret_key() -> bytes:
    key = os.environ.get("SECRET_KEY", "")
    if not key:
        if os.environ.get("RENDER") or os.environ.get("PRODUCTION"):
            raise RuntimeError("SECRET_KEY must be set in production")
        key = "dev-only-insecure-key"
    return key.encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Mix upper- and lower-case letters and at least one number."
    return None


def _sign(payload: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(secret_key(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_token(user_id: int, token_version: int) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{user_id}.{token_version}.{exp}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> tuple[int, int] | None:
    try:
        uid, ver, exp, sig = token.split(".")
    except ValueError:
        return None
    payload = f"{uid}.{ver}.{exp}"
    if not hmac.compare_digest(sig, _sign(payload)) or int(exp) < time.time():
        return None
    return int(uid), int(ver)


class RateLimiter:
    """Sliding-window limiter kept in memory (one web process)."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


login_limiter = RateLimiter(limit=8, window_s=300)
