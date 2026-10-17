#!/usr/bin/env python3
"""Minimal health probe for a CodeBuddy access token.

Exit codes: 0 = healthy, 2 = credentials rejected (re-login), 3 = other failure.

  python3 check.py            # one tiny streaming chat
  python3 check.py --refresh   # refresh first, then verify
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://copilot.tencent.com"
UA = "CodeBuddyIDE/1.106.1"
CRED = os.path.expanduser(os.environ.get("CODEBUDDY_CRED", "~/.hermes/codebuddy/credentials.json"))
PROBE_MODEL = os.environ.get("CODEBUDDY_PROBE_MODEL", "glm-5.3-flash")


def check() -> int:
    with open(CRED, encoding="utf-8") as fh:
        cred = json.load(fh)
    headers = {
        "Authorization": f"Bearer {cred['access_token']}",
        "X-Domain": cred.get("domain") or "www.codebuddy.cn",
        "X-Product": "CodeBuddy",
        "X-Product-Code": "codebuddy",
        "X-Agent-Purpose": "conversation",
        "X-IDE-Name": "CodeBuddy",
        "X-IDE-Type": "CodeBuddy",
        "X-IDE-Version": "1.106.1",
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = json.dumps({
        "model": PROBE_MODEL,
        "stream": True,
        # Reasoning models spend the budget on thinking: 64 is the safe minimum,
        # 8 gives an empty content field and a false "dead" verdict.
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Reply with: OK"}],
    }).encode()

    req = urllib.request.Request(f"{BASE}/v2/chat/completions", method="POST", headers=headers, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            got = ""
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                piece = line[5:].strip()
                if piece == "[DONE]":
                    break
                try:
                    delta = json.loads(piece)["choices"][0].get("delta") or {}
                except Exception:  # noqa: BLE001
                    continue
                got += (delta.get("content") or "") + (delta.get("reasoning_content") or "")
        if got.strip():
            print(f"OK alive: {got.strip()[:40]}")
            return 0
        print("ERROR alive: empty stream")
        return 3
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"ERROR alive http={e.code} {body[:300]}")
        return 2 if e.code in (401, 403) else 3
    except Exception as e:  # noqa: BLE001
        print(f"ERROR alive transport: {e}")
        return 3


if __name__ == "__main__":
    if "--refresh" in sys.argv[1:]:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from codebuddy_login import refresh  # noqa: E402
        refresh()
    sys.exit(check())
