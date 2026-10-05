#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beginner ke liye .env banane wala helper.

Chalao:  python scripts/setup_env.py

Ye ek-ek karke 5 values puchega, unhe .env file me likh dega.
Koi bhi value khaali chhod sakte ho (khali Enter dabao) - baad me bharna ho to
haath se .env edit kar lena, ya ye script dobara chala dena.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

FIELDS = [
    (
        "GROQ_API_KEY",
        "Groq ka API key",
        "console.groq.com/keys par jao, 'Create API Key' dabao. Value 'gsk_' se shuru hoti hai.",
    ),
    (
        "GOOGLE_CLIENT_ID",
        "Google OAuth ka Client ID",
        "Google Cloud > Credentials > apne 'Desktop app' client me dikhta hai (long number).",
    ),
    (
        "GOOGLE_CLIENT_SECRET",
        "Google OAuth ka Client Secret",
        "Same 'Desktop app' client me 'Client secret' ke saamne likha hota hai.",
    ),
    (
        "GOOGLE_REFRESH_TOKEN",
        "Blogger ka Refresh Token",
        "python scripts/get_refresh_token.py client_secret.json chalao. Value '1//' se shuru hoti hai.",
    ),
    (
        "BLOGGER_BLOG_ID",
        "Aapke blog ka ID",
        "Blogger dashboard kholo. URL me 'blogID=' ke baad jo number hai wahi hai (sirf digits).",
    ),
]


def clean_value(raw: str) -> str:
    """Spaces aur aas-paas ke quotes hata deta hai."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def ask_value(key: str, title: str, hint: str) -> str:
    print(f"\n--- {key} ---")
    print(f"Ye kya hai: {title}")
    print(f"Hint: {hint}")
    try:
        raw = input("Value paste karo (khali chhodne ke liye Enter dabao): ")
    except (EOFError, KeyboardInterrupt):
        print("\nChhod diya. .env nahi bana.", file=sys.stderr)
        raise SystemExit(1)
    return clean_value(raw)


def check_format(key: str, value: str) -> str | None:
    """Galat format ki chhoti si warning (fail nahi karta)."""
    if not value:
        return None
    if key == "GROQ_API_KEY" and not value.startswith("gsk_"):
        return "'gsk_' se shuru hona chahiye. Console se dobara copy karein?"
    if key == "BLOGGER_BLOG_ID" and not value.isdigit():
        return "ye sirf digits (numbers) ka hona chahiye, URL ya naam nahi."
    if key == "GOOGLE_REFRESH_TOKEN" and not value.startswith("1//"):
        return "'1//' se shuru hona chahiye. get_refresh_token.py se nikala hua token use karein."
    return None


def main() -> int:
    print("=" * 60)
    print(".env file banane wala helper (blogger-ai-agent)")
    print("=" * 60)
    print("Har value ke aage ek hint hai. Galat format ho to warning milegi.")
    print("Values screen par dikhengi - koi kaam nahi hai, bas dhyan rakhna.")

    if ENV_PATH.exists():
        print(f"\nDHYAN: {ENV_PATH.name} pehle se maujood hai.")
        try:
            answer = input("Uspar likhna hai? (y/N): ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancel kar diya.", file=sys.stderr)
            return 1
        if clean_value(answer).lower() not in ("y", "yes"):
            print("Theek hai, .env ko chhod diya. Kuch nahi badla.")
            return 0

    values: dict[str, str] = {}
    for key, title, hint in FIELDS:
        value = ask_value(key, title, hint)
        values[key] = value
        warning = check_format(key, value)
        if warning:
            print(f"  [WARNING] {warning}")
        elif value:
            print(f"  [saved] {key} ({len(value)} characters)")

    content = (
        "# Ye file me apni secret values rakhi hain. Kabhi bhi GitHub par push mat karo.\n"
        "# '=' ke aas-paas koi space ya quote mat rakho.\n\n"
        + "\n".join(f"{key}={values[key]}" for key, _, _ in FIELDS)
        + "\n"
    )
    try:
        ENV_PATH.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"\n[ERROR] .env likh nahi paya: {exc}")
        return 1

    print(f"\n{ENV_PATH.name} ban gayi. Ab kiya bhar hua:")
    for key, _, _ in FIELDS:
        print(f"  {'OK     ' if values[key] else 'EMPTY  '}{key}")

    empty = [key for key, _, _ in FIELDS if not values[key]]
    if empty:
        print(f"\nYe abhi khaali hain: {', '.join(empty)}")
        print("Inhe .env me khud bhar lo (ya ye script dobara chalao).")

    print("\nAgla step:  python scripts/agent.py --check")
    print("Sab OK aaye to:  python scripts/agent.py --dry-run")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nCancel kar diya.", file=sys.stderr)
        sys.exit(1)