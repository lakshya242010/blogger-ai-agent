#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ek baar chalane wala script - Google se Refresh Token nikalne ke liye.

Ye script sirf aapke laptop par chalta hai, GitHub par nahi.
Iske liye ye install karo:
    pip install google-auth-oauthlib

Phir chalao:
    python scripts/get_refresh_token.py client_secret.json

client_secret.json Google Cloud se download ki hui file hai (Desktop app client).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/blogger"]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python scripts/get_refresh_token.py <client_secret.json>")
        print("Example: python scripts/get_refresh_token.py client_secret.json")
        return 1

    secrets_path = Path(argv[1])
    if not secrets_path.is_file():
        print(f"[ERROR] File nahi mili: {secrets_path}")
        print("Google Cloud > APIs & Services > Credentials se Desktop app ka JSON download karo.")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[ERROR] google-auth-oauthlib install nahi hai.")
        print("Ye chalane se pehle chalao:  pip install google-auth-oauthlib")
        return 1

    print("Browser khul raha hai... Google me login karke 'Allow' dabao.")
    print("(Agar browser na khule to redhast link terminal me dikhega, usse copy karke kholo.)")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    except Exception as exc:  # noqa: BLE001 - user ke ghar me aksar network/localhost issue hota hai
        print(f"[ERROR] Login fail hua: {exc}")
        print("Common reasons: port band hai, ya OAuth consent screen 'In production' me nahi hai.")
        return 1

    # Google aksar credentials.json me client id/secret nahi deta, to file se uthate hain.
    client_id = (getattr(creds, "client_id", "") or "").strip()
    client_secret = (getattr(creds, "client_secret", "") or "").strip()
    refresh_token = (getattr(creds, "refresh_token", "") or "").strip()

    if not (client_id and client_secret):
        try:
            raw = json.loads(secrets_path.read_text(encoding="utf-8"))
            section = raw.get("installed") or raw.get("web") or {}
            client_id = client_id or str(section.get("client_id", "")).strip()
            client_secret = client_secret or str(section.get("client_secret", "")).strip()
        except (OSError, ValueError):
            pass

    if not refresh_token:
        print("\n[ERROR] Refresh token nahi mila.")
        print("Reasons: consent screen 'Testing' me hai (ya 'External' + apne khud ke app ko add nahi kiya),")
        print("ya pehle se koi access diya gaya tha isliye naya token nahi bana.")
        print("Fix: OAuth consent screen ko 'In production' karo, phir dobara chalao.")
        return 1

    print("\n=== Ye 3 values mil gayi. Ise .env me copy kar lo ===")
    print(f"\nGOOGLE_CLIENT_ID={client_id}")
    print(f"\nGOOGLE_CLIENT_SECRET={client_secret}")
    print(f"\nGOOGLE_REFRESH_TOKEN={refresh_token}")
    print("\nSabse aasan tareeka: ye 3 values seedha paste kar do ->  python scripts/setup_env.py")
    print("Note: ye values galti se kisi ko mat bhejo. Ye log-in ka access hain.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))