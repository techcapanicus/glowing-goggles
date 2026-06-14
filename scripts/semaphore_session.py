#!/usr/bin/env python3
"""Semaphore session helper: API Bearer token (preferred) or username/password login."""
from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SemaphoreSession:
    """HTTP client for Semaphore with Bearer token or login cookie."""

    def __init__(self, base_url: str, token: str = "", cookie_jar=None):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.cookie_jar = cookie_jar or http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def _headers(self, with_json: bool = False) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": BROWSER_UA,
        }
        if with_json:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, payload=None, timeout: int = 60):
        url = f"{self.base_url}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=self._headers(with_json=payload is not None),
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} -> network error: {exc.reason}") from exc

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, payload=None):
        return self.request("POST", path, payload)

    def ping(self) -> bool:
        try:
            result = self.get("/api/ping")
            if isinstance(result, dict):
                return result.get("message") == "pong"
            if isinstance(result, str):
                return result.strip() == "pong"
            return False
        except RuntimeError:
            return False

    def user(self):
        return self.get("/api/user")


def login(base_url: str, username: str, password: str) -> SemaphoreSession:
    session = SemaphoreSession(base_url)
    session.post("/api/auth/login", {"auth": username, "password": password})
    me = session.user()
    if not me or not me.get("username"):
        raise RuntimeError("Login failed: /api/user did not return a user")
    return session


def from_env_or_login(
    url: str | None = None,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    *,
    url_explicit: bool = False,
) -> SemaphoreSession:
    """Authenticate to Semaphore.

    Priority:
      1. Explicit ``token`` argument (--token)
      2. SEMAPHORE_TOKEN env (skipped when --url points at a different host)
      3. username + password (CLI or env) as a fallback
    """
    base = (url or os.environ.get("SEMAPHORE_URL", "")).rstrip("/")
    if not base:
        raise RuntimeError("Set SEMAPHORE_URL or pass --url")

    if token:
        session = SemaphoreSession(base, token=token)
        session.user()
        return session

    user = username or os.environ.get("SEMAPHORE_USERNAME", "")
    pwd = password or os.environ.get("SEMAPHORE_PASSWORD", "")
    if user and pwd:
        return login(base, user, pwd)

    env_url = os.environ.get("SEMAPHORE_URL", "").rstrip("/")
    env_tok = os.environ.get("SEMAPHORE_TOKEN", "")
    # Use .env token only when URL was not overridden to a different instance.
    if env_tok and not (url_explicit and env_url and base != env_url):
        session = SemaphoreSession(base, token=env_tok)
        session.user()
        return session

    raise RuntimeError(
        "Provide --token / SEMAPHORE_TOKEN (copy from browser Network tab: "
        "any /api/* request → Authorization: Bearer …) or username + password"
    )
