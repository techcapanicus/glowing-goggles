#!/usr/bin/env python3
"""Test all discovered API keys against provider endpoints."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.semaphore_session import from_env_or_login  # noqa: E402

DID_KEYWORDS = ("telnyx", "did", "twilio", "plivo", "bandwidth", "vonage", "nexmo", "sendgrid", "stripe", "didww")
KEY_SUFFIXES = ("_key", "_api_key", "_token", "_secret", "_auth")


def curl_test(name: str, url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(500).decode("utf-8", "replace")
            return {"name": name, "status": resp.status, "ok": 200 <= resp.status < 300, "body": body[:200]}
    except urllib.error.HTTPError as e:
        body = e.read(300).decode("utf-8", "replace")
        return {"name": name, "status": e.code, "ok": False, "body": body[:200]}
    except Exception as e:
        return {"name": name, "status": 0, "ok": False, "body": str(e)}


def test_telnyx(key: str) -> list[dict]:
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    return [
        curl_test("telnyx_balance", "https://api.telnyx.com/v2/balance", h),
        curl_test("telnyx_profiles", "https://api.telnyx.com/v2/messaging_profiles?page[size]=1", h),
    ]


def test_sendgrid(key: str) -> list[dict]:
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    return [curl_test("sendgrid_scopes", "https://api.sendgrid.com/v3/scopes", h)]


def test_stripe(key: str) -> list[dict]:
    import base64
    auth = base64.b64encode(f"{key}:".encode()).decode()
    h = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    return [curl_test("stripe_balance", "https://api.stripe.com/v1/balance", h)]


def collect_keys_from_semaphore(session) -> dict[str, set]:
    keys: dict[str, set] = {"telnyx": set(), "sendgrid": set(), "stripe": set(), "other": set()}
    for p in session.get("/api/projects") or []:
        pid = p["id"]
        for env in session.get(f"/api/project/{pid}/environment") or []:
            raw = env.get("json") or ""
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for k, v in obj.items():
                if not isinstance(v, str) or len(v) < 8:
                    continue
                kl = k.lower()
                if "telnyx" in kl and ("key" in kl or kl.endswith("_key")):
                    keys["telnyx"].add(v)
                elif "did_api" in kl or kl == "did_api_key":
                    keys["telnyx"].add(v)
                elif "sendgrid" in kl and "key" in kl:
                    keys["sendgrid"].add(v)
                elif "stripe" in kl and "secret" in kl:
                    keys["stripe"].add(v)
    return keys


def main():
    session = from_env_or_login()
    keys = collect_keys_from_semaphore(session)
    results = []
    for key in keys["telnyx"]:
        masked = key[:12] + "..." + key[-6:] if len(key) > 20 else key
        print(f"\n=== Telnyx key {masked} ===")
        for r in test_telnyx(key):
            print(f"  {r['name']}: HTTP {r['status']} ok={r['ok']}")
            if not r["ok"]:
                print(f"    {r['body'][:150]}")
            results.append({"provider": "telnyx", "key_mask": masked, **r})
    for key in keys["sendgrid"]:
        masked = key[:10] + "..."
        print(f"\n=== SendGrid key {masked} ===")
        for r in test_sendgrid(key):
            print(f"  {r['name']}: HTTP {r['status']} ok={r['ok']}")
            results.append({"provider": "sendgrid", "key_mask": masked, **r})
    for key in keys["stripe"]:
        masked = key[:12] + "..."
        print(f"\n=== Stripe key {masked} ===")
        for r in test_stripe(key):
            print(f"  {r['name']}: HTTP {r['status']} ok={r['ok']}")
            results.append({"provider": "stripe", "key_mask": masked, **r})

    out = "/tmp/api_key_test_results.json"
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nSaved {len(results)} test results to {out}")
    working = [r for r in results if r.get("ok")]
    print(f"Working keys: {len(working)}/{len(results)}")


if __name__ == "__main__":
    main()
