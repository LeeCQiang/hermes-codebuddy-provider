#!/usr/bin/env python3
"""CodeBuddy (Tencent) credential helper for Hermes Agent.

Two commands:

  codebuddy_login.py login     # interactive: prints a URL, waits for the token
  codebuddy_login.py refresh   # refresh access_token in place

Credentials are stored in ~/.hermes/codebuddy/credentials.json (mode 0600) and the
access token is mirrored into ~/.hermes/.env as CODEBUDDY_ACCESS_TOKEN.

No third-party dependencies. Python 3.8+.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://copilot.tencent.com"
UA = "CodeBuddyIDE/1.106.1"
CRED = os.path.expanduser(os.environ.get("CODEBUDDY_CRED", "~/.hermes/codebuddy/credentials.json"))
ENV = os.path.expanduser(os.environ.get("CODEBUDDY_ENV", "~/.hermes/.env"))
ENV_KEY = "CODEBUDDY_ACCESS_TOKEN"


def _req(url: str, method: str = "GET", headers: dict | None = None, data: bytes = b""):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data or None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def _pick(d: dict, *keys, default=None):
    """Dig through nested responses without assuming one exact shape."""
    stack = [d]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k in keys:
                if k in cur and cur[k]:
                    return cur[k]
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return default


def save_cred(data: dict) -> None:
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    tmp = CRED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CRED)


def sync_env(token: str) -> None:
    """Update only the CODEBUDDY_ACCESS_TOKEN line in .env, keeping permissions."""
    lines: list[str] = []
    try:
        with open(ENV, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        pass
    for i, line in enumerate(lines):
        if line.startswith(ENV_KEY + "="):
            lines[i] = f"{ENV_KEY}={token}"
            break
    else:
        lines.append(f"{ENV_KEY}={token}")
    with open(ENV, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


def login(poll_seconds: int = 300) -> int:
    status, body = _req(f"{BASE}/v2/plugin/auth/state?platform=ide", "POST",
                        {"User-Agent": UA, "Content-Type": "application/json"}, b"{}")
    if status != 200:
        print(f"ERROR state http={status} {body[:300]}")
        return 3

    payload = json.loads(body)
    state = _pick(payload, "state", "authState")
    url = _pick(payload, "authUrl", "loginUrl", "url")
    if not state or not url:
        print(f"ERROR unexpected state response: {body[:300]}")
        return 3

    print("Open this URL in a browser and sign in with your CodeBuddy account:\n")
    print(f"  {url}\n")
    print(f"Waiting up to {poll_seconds}s for the token ...")

    deadline = time.time() + poll_seconds
    while time.time() < deadline:
        st, bd = _req(f"{BASE}/v2/plugin/auth/token?state={state}", "GET",
                      {"User-Agent": UA, "Accept": "application/json"})
        if st == 200:
            data = json.loads(bd)
            at = _pick(data, "accessToken", "access_token")
            if at:
                save_cred({
                    "access_token": at,
                    "refresh_token": _pick(data, "refreshToken", "refresh_token", default=""),
                    "domain": _pick(data, "domain", default="www.codebuddy.cn"),
                    "scope": _pick(data, "scope", default=""),
                    "token_type": _pick(data, "tokenType", default="Bearer"),
                    "expires_in": _pick(data, "expiresIn", default=0),
                    "refresh_expires_in": _pick(data, "refreshExpiresIn", default=0),
                    "obtained_at": time.time(),
                })
                sync_env(at)
                print(f"\nOK  token saved to {CRED} (0600) and mirrored into {ENV}")
                print(f"    access_token valid for {round((_pick(data, 'expiresIn', default=0) or 0) / 86400, 1)} days")
                return 0
        elif st in (401, 403, 404):
            pass  # not authorized yet — keep polling
        time.sleep(3)
    print("ERROR timed out waiting for login")
    return 2


def refresh() -> int:
    with open(CRED, encoding="utf-8") as fh:
        cred = json.load(fh)
    at = cred["access_token"]
    rt = cred["refresh_token"]
    dom = cred.get("domain") or "www.codebuddy.cn"
    headers = {
        "Authorization": f"Bearer {at}",
        "X-Refresh-Token": rt,
        "X-Auth-Refresh-Source": "ide-main",
        "X-Domain": dom,
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    status, body = _req(f"{BASE}/v2/plugin/auth/token/refresh", "POST", headers, b"{}")
    if status != 200:
        print(f"ERROR refresh http={status} {body[:300]}")
        low = body.lower()
        return 2 if (status in (401, 403) or "expired" in low or "invalid" in low) else 3

    data = json.loads(body)
    new_at = _pick(data, "accessToken")
    if not new_at:
        print(f"ERROR no accessToken in response: {body[:200]}")
        return 3

    cred.update({
        "access_token": new_at,
        "refresh_token": _pick(data, "refreshToken", default=rt),
        "domain": _pick(data, "domain", default=dom),
        "expires_in": _pick(data, "expiresIn", default=cred.get("expires_in")),
        "refresh_expires_in": _pick(data, "refreshExpiresIn", default=cred.get("refresh_expires_in")),
        "obtained_at": time.time(),
    })
    save_cred(cred)
    sync_env(new_at)
    print(f"OK  refreshed (expires in {round((cred.get('expires_in') or 0) / 86400, 1)} days)")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    sys.exit({"login": login, "refresh": refresh}.get(cmd, lambda: (print("usage: login|refresh"), 1)[1])())
