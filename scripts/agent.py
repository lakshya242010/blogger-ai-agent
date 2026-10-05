#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous blogging agent (Groq + Blogger).

Ye script do jagah chalta hai:
  1. Local (VS Code)  ->  python scripts/agent.py --check | --dry-run | --now
  2. GitHub Actions   ->  har 15 minute me automatically

Din ke time slots config.json me diye hain (sab IST = UTC+5:30, HH:MM 24-hour).
Har slot par agent apne aap:
  1. Internet par topic dhoondhta hai
  2. Research karke article likhta hai
  3. Edit/proofread karta hai
  4. Blogger par draft ya publish karta hai (config.json ke "mode" ke hisaab se)

Sirf ek dependency chahiye: requests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Paths aur constants
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
PREVIEW_DIR = ROOT / "preview"

IST = timezone(timedelta(hours=5, minutes=30))

REQUIRED_ENV_VARS = [
    "GROQ_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "BLOGGER_BLOG_ID",
]

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API = "https://www.googleapis.com/blogger/v3"
GOOGLE_SCOPES = "https://www.googleapis.com/auth/blogger"

# groq/compound 21 September 2026 ko retire ho chuka hai (Groq docs dekh lo).
# Ab built-in web search ke liye "openai/gpt-oss-120b" + tools=[{"type":"browser_search"}]
# use hota hai. Dono ko env se badla ja sakta hai.
DEFAULT_SEARCH_MODEL = "openai/gpt-oss-120b"
DEFAULT_EDIT_MODEL = "openai/gpt-oss-120b"

HTTP_TIMEOUT = (30, 300)
RATE_LIMIT_RETRIES = 4
MIN_ARTICLE_CHARS = 300
MAX_SOURCES = 5
MAX_LABELS = 5
MAX_TITLES = 200
KEEP_STATE_ENTRIES = 60
MAX_ATTEMPTS = 3
GRACE_HOURS = 6


class AgentError(Exception):
    """Agent ka apna error - message user ko saaf dikhna chahiye."""


# --------------------------------------------------------------------------
# Chhote helpers (env, config, state)
# --------------------------------------------------------------------------


def load_env(path: str | os.PathLike | None = None) -> bool:
    """.env padhta hai aur os.environ me set karta hai (python-dotenv ki zarurat nahi).

    - comment (#) aur khali lines ignore hoti hain
    - key=value ke aas-paas spaces hat jaate hain
    - value ke aas-paas ke quotes hat jaate hain
    - pehle se set env var ko overwrite NAHI karta (setdefault)
    """
    env_path = Path(path) if path else ROOT / ".env"
    if not env_path.is_file():
        return False
    try:
        raw_text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AgentError(f".env padha nahi ja saka: {exc}") from exc

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
    return True


def load_config() -> dict:
    """config.json padhta hai aur jaanch karta hai ki sahi format hai."""
    if not CONFIG_PATH.is_file():
        raise AgentError(f"config.json nahi mila: {CONFIG_PATH}")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentError(f"config.json sahi JSON nahi hai: {exc}") from exc
    if not isinstance(cfg, dict):
        raise AgentError("config.json me object hona chahiye.")

    cfg.setdefault("enabled", True)
    cfg.setdefault("mode", "draft")
    cfg.setdefault("niche", "Technology and AI")
    cfg.setdefault("language", "Hinglish (Roman Hindi + English)")
    cfg.setdefault("tone", "friendly, simple, beginner-friendly")
    cfg.setdefault("word_count", 900)
    cfg.setdefault("slots", [])

    if str(cfg.get("mode", "draft")).lower() not in ("draft", "publish"):
        raise AgentError('config.json me "mode" ya "draft" ya "publish" hona chahiye.')
    cfg["mode"] = str(cfg.get("mode", "draft")).lower()

    slots = cfg.get("slots")
    if not isinstance(slots, list) or not slots:
        raise AgentError('config.json me "slots" ki kam se kam ek entry honi chahiye.')

    clean_slots = []
    for slot in slots:
        if not isinstance(slot, dict) or "time" not in slot:
            raise AgentError('Har slot me "time" (jaise "09:00") hona chahiye.')
        hh, mm = str(slot["time"]).strip().split(":")[:2]
        hh, mm = hh.strip(), mm.strip()
        if not (hh.isdigit() and mm.isdigit()) or not (0 <= int(hh) <= 23) or not (0 <= int(mm) <= 59):
            raise AgentError(f'Slot time galat hai: {slot["time"]!r}. Format "HH:MM" (24-hour) chahiye.')
        clean_slots.append({
            "time": f"{int(hh):02d}:{int(mm):02d}",
            "focus": str(slot.get("focus", "general blogging topic")).strip(),
        })
    cfg["slots"] = clean_slots

    try:
        cfg["word_count"] = int(cfg.get("word_count", 900))
    except (TypeError, ValueError):
        cfg["word_count"] = 900
    return cfg


def default_state() -> dict:
    return {"done": {}, "attempts": {}, "titles": []}


def load_state() -> dict:
    """state.json padhta hai. Na hua ya bigadu hua to naya state bana deta hai."""
    state = default_state()
    if not STATE_PATH.is_file():
        return state
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] state.json padha nahi ja saka ({exc}), naya state use kar raha hoon.", file=sys.stderr)
        return state
    if not isinstance(raw, dict):
        return state
    done = raw.get("done")
    attempts = raw.get("attempts")
    titles = raw.get("titles")
    state["done"] = done if isinstance(done, dict) else {}
    state["attempts"] = attempts if isinstance(attempts, dict) else {}
    state["titles"] = [str(t) for t in titles] if isinstance(titles, list) else []
    return state


def prune_state(state: dict) -> dict:
    """done aur attempts ko latest 60 entries tak kaata hai, titles ko 200 tak."""
    done = state.get("done", {})
    attempts = state.get("attempts", {})
    state["done"] = {k: done[k] for k in sorted(done.keys())[-KEEP_STATE_ENTRIES:]}
    state["attempts"] = {k: attempts[k] for k in sorted(attempts.keys())[-KEEP_STATE_ENTRIES:]}
    state["titles"] = list(state.get("titles", []))[-MAX_TITLES:]
    return state


def save_state(state: dict) -> None:
    """state.json ko turant disk par likhta hai (har slot ke baad)."""
    pruned = prune_state(state)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(pruned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def now_ist() -> datetime:
    return datetime.now(IST)


def search_model() -> str:
    return (os.environ.get("GROQ_SEARCH_MODEL") or DEFAULT_SEARCH_MODEL).strip()


def edit_model() -> str:
    return (os.environ.get("GROQ_EDIT_MODEL") or DEFAULT_EDIT_MODEL).strip()


def short_body(resp, limit: int = 300) -> str:
    """Error ka response body chhota karke wapas deta hai (secrets kabhi print nahi hote)."""
    try:
        text = resp.text or ""
    except Exception:  # noqa: BLE001 - body padhna fail ho jaye to bhi error dikhana hai
        text = ""
    text = " ".join(text.split())
    return text[:limit]


# --------------------------------------------------------------------------
# Groq API
# --------------------------------------------------------------------------


def extract_sources(message) -> list[tuple[str, str]]:
    """Groq ke search result se REAL urls nikalta hai.

    message["executed_tools"] ko recursively walk karta hai aur har dict me se
    "url" (http se start hona chahiye) uthata hai. Ye urls asli search ke hain,
    model ne khud nahi banaye. Max 5, duplicate hatake.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and url.startswith("http"):
                key = url.rstrip("/")
                if key not in seen:
                    seen.add(key)
                    raw_title = node.get("title")
                    title = str(raw_title).strip() if raw_title else ""
                    found.append((title or url, url))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    tools = message.get("executed_tools") if isinstance(message, dict) else None
    if tools:
        walk(tools)
    if not found:
        # Future-proof fallback: koi naya field aaye to bhi urls mil jayen.
        walk(message)
    return found[:MAX_SOURCES]


def _retry_after_seconds(resp, attempt: int) -> int:
    """429 ke baad kitni der wait karni hai (20s * attempt, max 90s)."""
    default_wait = min(90, 20 * attempt)
    header = None
    try:
        header = resp.headers.get("retry-after") if resp.headers else None
    except Exception:  # noqa: BLE001
        header = None
    if not header:
        return default_wait
    try:
        return max(1, min(90, int(str(header).strip())))
    except ValueError:
        return default_wait


def ask(prompt: str, system: str | None = None, use_search: bool = False,
        max_tokens: int | None = None, temperature: float = 1.0) -> tuple[str, list[tuple[str, str]]]:
    """Groq chat completion call karta hai. Returns (text, sources)."""
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise AgentError("GROQ_API_KEY missing hai. .env banao ya env var set karo.")

    model = search_model() if use_search else edit_model()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        payload["max_completion_tokens"] = int(max_tokens)

    # Optional: kuch models reasoning_effort nahi maante, isliye default me bhejte nahi.
    effort = (os.environ.get("GROQ_REASONING_EFFORT") or "").strip()
    if effort:
        payload["reasoning_effort"] = effort

    if use_search:
        if "compound" in model.lower():
            # Purane compound systems me web search built-in tha, tools nahi bhejne the.
            pass
        else:
            # Naya tareeka: built-in browser_search tool (server side chalta hai).
            payload["tools"] = [{"type": "browser_search"}]
            payload["tool_choice"] = "required"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    response = None
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            response = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise AgentError(f"Groq se connection nahi hua: {exc}") from exc

        if response.status_code == 429:
            if attempt >= RATE_LIMIT_RETRIES:
                raise AgentError(
                    f"Groq rate limit (429) {RATE_LIMIT_RETRIES + 1} baar bhi aaya. "
                    f"Thodi der baad dobara try karo. Response: {short_body(response)}"
                )
            wait = _retry_after_seconds(response, attempt + 1)
            print(f"      [rate limit] {wait}s wait kar raha hoon, phir try karunga...")
            time.sleep(wait)
            continue
        break

    if response.status_code >= 400:
        hint = ""
        body = short_body(response)
        if response.status_code == 400 and "model" in body.lower():
            hint = (f"\n      Model '{model}' shayad retire ho chuka hai ya built-in search support nahi karta. "
                    f"GROQ_SEARCH_MODEL / GROQ_EDIT_MODEL env var se badal sakte ho.")
        raise AgentError(f"Groq API error {response.status_code}: {body}{hint}")

    try:
        data = response.json()
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AgentError(f"Groq ka response samajh nahi aaya: {exc}. Response: {short_body(response)}") from exc

    text = (message.get("content") or "").strip()
    if not text:
        # Reasoning models kabhi kabhi sirf reasoning field bhar dete hain.
        text = (message.get("reasoning") or "").strip()
    if not text:
        raise AgentError("Groq ne khaali text return kiya.")

    return text, extract_sources(message)


# --------------------------------------------------------------------------
# Article parsing
# --------------------------------------------------------------------------


def _clean_body(body: str) -> str:
    """Model ke galti se aaye html/head/body tags aur ``` fences hata deta hai."""
    text = body.strip()
    if text.startswith("```"):
        first, _, rest = text.partition("\n")
        text = rest if "```" in first else text
    if text.endswith("```"):
        text = text[:-3].rstrip()
    text = re.sub(r"(?is)<\s*head\b.*?<\s*/\s*head\s*>", "", text)
    for tag in ("html", "head", "body"):
        text = re.sub(rf"(?i)<\s*/?\s*{tag}\b[^>]*>", "", text)
    return text.strip()


def parse_article(text: str) -> tuple[str, list[str], str]:
    """TITLE/LABELS/===HTML=== format wala text parse karta hai.

    Returns (title, labels, html_body)
    """
    if "===HTML===" not in text:
        raise AgentError(
            "Article ka format galat hai: '===HTML===' line nahi mili. "
            "Model ko OUTPUT FORMAT exactly follow karwao."
        )

    head, _, body = text.partition("===HTML===")

    title = ""
    labels: list[str] = []
    for line in head.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("TITLE:"):
            title = stripped[len("TITLE:"):].strip()
        elif upper.startswith("LABELS:"):
            labels = [item.strip() for item in stripped[len("LABELS:"):].split(",")]

    title = title.strip().strip("*#").strip()
    labels = [item.strip(" \"'#*") for item in labels]
    labels = [item for item in labels if item][:MAX_LABELS]

    html_body = _clean_body(body)

    if not title:
        raise AgentError("Article ka title nahi mila (TITLE: line missing hai).")
    if len(html_body) < MIN_ARTICLE_CHARS:
        raise AgentError(
            f"Article ka body bahut chhota hai ({len(html_body)} characters). "
            f"Kam se kam {MIN_ARTICLE_CHARS} characters chahiye."
        )
    return title, labels, html_body


def sources_html(sources: list[tuple[str, str]]) -> str:
    """Real search urls se ek chhota Sources section banata hai."""
    if not sources:
        return ""
    items = []
    for title, url in sources[:MAX_SOURCES]:
        safe_title = escape(str(title).strip() or url, quote=True)
        safe_url = escape(str(url), quote=True)
        items.append(f'    <li><a href="{safe_url}" rel="nofollow noopener">{safe_title}</a></li>')
    return '<h3>Sources</h3>\n<ul>\n' + "\n".join(items) + "\n</ul>"


def preview_page(title: str, labels: list[str], body_html: str, sources: list[tuple[str, str]]) -> str:
    """--dry-run ke liye readable HTML page (browser me kholo aur dekho)."""
    label_html = ""
    if labels:
        chips = "".join(f'<span class="chip">{escape(label, quote=True)}</span>' for label in labels)
        label_html = f'<p class="labels">{chips}</p>'
    return (
        "<!DOCTYPE html>\n"
        '<html lang="hi">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title, quote=True)}</title>\n"
        "<style>\n"
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
        "max-width:760px;margin:40px auto;padding:0 18px;line-height:1.7;color:#1b1b1b}\n"
        "h1{line-height:1.25}\n"
        ".labels .chip{display:inline-block;background:#eef2ff;border-radius:999px;"
        "padding:2px 12px;margin:0 6px 6px 0;font-size:13px}\n"
        ".meta{color:#666;font-size:13px}\n"
        "</style>\n</head>\n<body>\n"
        f"<p class=\"meta\">Preview (dry-run) - ye post abhi Blogger par nahi gaya</p>\n"
        f"<h1>{escape(title, quote=True)}</h1>\n"
        f"{label_html}\n"
        f"{body_html}\n"
        f"{sources_html(sources)}\n"
        "</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
# Blogger API
# --------------------------------------------------------------------------


def google_access_token() -> str:
    """Refresh token ko access token me badalta hai (har run par naya token)."""
    client_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
    refresh_token = (os.environ.get("GOOGLE_REFRESH_TOKEN") or "").strip()
    missing = [name for name, value in (
        ("GOOGLE_CLIENT_ID", client_id),
        ("GOOGLE_CLIENT_SECRET", client_secret),
        ("GOOGLE_REFRESH_TOKEN", refresh_token),
    ) if not value]
    if missing:
        raise AgentError(f"Ye env var missing hain: {', '.join(missing)}")

    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=(20, 60),
        )
    except requests.RequestException as exc:
        raise AgentError(f"Google token server se connect nahi hua: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(f"Google token error {response.status_code}: {short_body(response)}")
    try:
        token = response.json().get("access_token")
    except ValueError as exc:
        raise AgentError(f"Google token response samajh nahi aaya: {exc}. Response: {short_body(response)}") from exc
    if not token:
        raise AgentError(f"Google ne access token nahi diya. Response: {short_body(response)}")
    return token


def blogger_get_blog(token: str, blog_id: str) -> dict:
    """Blog ki info leta hai (--check me blog name dikhane ke liye)."""
    url = f"{BLOGGER_API}/blogs/{blog_id}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(20, 60),
        )
    except requests.RequestException as exc:
        raise AgentError(f"Blogger se connect nahi hua: {exc}") from exc
    if response.status_code >= 400:
        raise AgentError(f"Blogger blog info error {response.status_code}: {short_body(response)}")
    try:
        return response.json()
    except ValueError as exc:
        raise AgentError(f"Blogger blog info samajh nahi aaya: {exc}. Response: {short_body(response)}") from exc


def blogger_create_post(token: str, blog_id: str, title: str, labels: list[str],
                        body_html: str, as_draft: bool) -> dict:
    """Blogger par naya post banata hai (draft ya live)."""
    url = f"{BLOGGER_API}/blogs/{blog_id}/posts/"
    if as_draft:
        url += "?isDraft=true"
    payload: dict = {"title": title, "content": body_html}
    if labels:
        payload["labels"] = labels
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=(20, 120),
        )
    except requests.RequestException as exc:
        raise AgentError(f"Blogger post bhi nahi ban paya: {exc}") from exc
    if response.status_code >= 400:
        raise AgentError(f"Blogger post error {response.status_code}: {short_body(response)}")
    try:
        return response.json()
    except ValueError as exc:
        raise AgentError(f"Blogger ka response samajh nahi aaya: {exc}. Response: {short_body(response)}") from exc


# --------------------------------------------------------------------------
# Char steps
# --------------------------------------------------------------------------


SEARCH_SYSTEM = (
    "You are a careful research assistant. You browse the live web, so only state facts "
    "you actually found on the web, and never invent links, dates or numbers. "
    "You always answer in the exact output format the user asks for."
)


def first_json_block(text: str) -> str | None:
    """Text me pehla {...} block nikalta hai (chhota regex + brace counting fallback)."""
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        return match.group(0)

    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if start == -1:
                start = index
            depth += 1
        elif char == "}" and start != -1:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def pick_topic(cfg: dict, focus: str, recent_titles: list[str], today: str) -> tuple[str, str]:
    """Step 1: internet par topic dhoondhta hai. Returns (topic, angle)."""
    print("1/4 Topic dhoondh raha hoon...")
    recent_block = "\n".join(f"- {t}" for t in recent_titles[-40:]) or "- (abhi koi topic nahi)"
    word_count = cfg["word_count"]
    prompt = f"""Aaj ki date: {today}
Blog ka niche: {cfg['niche']}
Is time slot ka focus: {focus}
Article ka language: {cfg['language']}
Target length: {word_count} words

Mere blog par pehle se ye topics aa chuke hain. IN PAR bilkul naya topic mat do:
{recent_block}

Task: Live internet par search karo aur ek fresh, useful aur relevant topic chuno.
Topic aaj ke time ke latest updates/news/tutorials par based ho, aur readers ko fayda ho.
Topic specific hona chahiye, bilkul generic nahi.

OUTPUT: Sirf JSON do, koi extra text, markdown ya explanation nahi:
{{"topic": "chhota, specific topic", "angle": "article kis nazar se likha jayega - ek line"}}
"""
    text, _ = ask(prompt, system=SEARCH_SYSTEM, use_search=True, max_tokens=1200, temperature=0.6)

    raw_json = first_json_block(text)
    if not raw_json:
        raise AgentError(f"Topic JSON nahi mila. Model ka text: {text[:200]}")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise AgentError(f"Topic JSON parse nahi hua: {exc}. Text: {raw_json[:200]}") from exc
    if not isinstance(data, dict):
        raise AgentError("Topic JSON me object expected tha.")

    topic = str(data.get("topic", "")).strip()
    angle = str(data.get("angle", "")).strip()
    if not topic:
        raise AgentError(f"Topic JSON me 'topic' khaali hai. Text: {raw_json[:200]}")
    if not angle:
        angle = topic
    print(f"      Topic: {topic}")
    return topic, angle


def write_article(cfg: dict, topic: str, angle: str) -> tuple[str, list[tuple[str, str]]]:
    """Step 2: research karke article ka raw draft likhta hai."""
    print("2/4 Research karke article likh raha hoon...")
    word_count = cfg["word_count"]
    max_tokens = int(word_count * 2.5) + 1500
    prompt = f"""Ek blog article likho.

Topic: {topic}
Nazar (angle): {angle}
Niche: {cfg['niche']}
Language: {cfg['language']}
Tone: {cfg['tone']}
Target length: {word_count} words (roughly)

Rules:
- Live internet par research karo. Sirf wahi facts likho jo search me mila. Galat date, number ya naam mat likho.
- Apne apne words me likho. Kisi site ka text copy mat karo.
- <h2> aur <h3> headings use karo. Paragraph chhote rakho (2-3 lines max).
- <p>, <ul>/<li>, <strong> jaise simple HTML tags use karo.
- IMPORTANT: <html>, <head>, <body>, <h1> tags mat likho.
- IMPORTANT: "Sources" ya "References" section mat likho.
- IMPORTANT: apne man se koi link (URL) mat banao. Links main code me khud add karunga.

OUTPUT (bilkul isi format me, iske bahar kuch nahi):
TITLE: <title>
LABELS: <3-5 labels, comma se separated>
===HTML===
<html body>
"""
    return ask(prompt, system=SEARCH_SYSTEM, use_search=True, max_tokens=max_tokens)


EDIT_SYSTEM = (
    "You are a meticulous editor. You improve grammar, flow and clarity, you remove "
    "filler and AI-sounding phrases, and you never change facts or invent anything new."
)


def edit_article(cfg: dict, draft_text: str) -> tuple[str, list[str], str]:
    """Step 3: alag step me proofread/edit. Agar fail ho jaye to raw draft use hoga."""
    print("3/4 Article ko edit/proofread kar raha hoon...")
    max_tokens = int(cfg["word_count"] * 2.5) + 2000
    prompt = f"""Neeche ek blog article ka raw draft hai. Ise professionally edit karke do.

Rules:
- Grammar, spelling aur punctuation theek karo.
- Duplicate baatein aur bekaar sentences hata do.
- Aise generic AI-jaise phrases hata do (jaise "In today's fast-paced world", "It is important to note that").
- Headings aur flow behtar karo. H2/H3 headings rakho.
- Facts, numbers aur links BILKUL mat badlo. Koi naya link mat banao.
- Title 70 characters se chhota rakho.
- Language: {cfg['language']}. Tone: {cfg['tone']}.
- IMPORTANT: "Sources" ya "References" section mat banao.
- IMPORTANT: <html>, <head>, <body>, <h1> tags mat likho.

RAW DRAFT:
{draft_text}

OUTPUT (bilkul isi format me, iske bahar kuch nahi):
TITLE: <title>
LABELS: <3-5 labels, comma se separated>
===HTML===
<html body>
"""
    try:
        edited_text, _ = ask(prompt, system=EDIT_SYSTEM, use_search=False, max_tokens=max_tokens, temperature=0.3)
        title, labels, html_body = parse_article(edited_text)
    except (AgentError, ValueError, KeyError) as exc:
        print(f"      [warn] Edit step fail hua ({exc}). Raw draft as-is post kar raha hoon.", file=sys.stderr)
        title, labels, html_body = parse_article(draft_text)

    if len(title) > 70:
        print(f"      [warn] Title {len(title)} characters ka hai, 70 se lamba hai.", file=sys.stderr)
    return title, labels, html_body


def publish(cfg: dict, title: str, labels: list[str], html_body: str,
            sources: list[tuple[str, str]]) -> dict:
    """Step 4: sources jodkar Blogger par post (ya draft) karta hai."""
    as_draft = cfg["mode"] != "publish"
    kind = "DRAFT" if as_draft else "PUBLISHED"
    print(f"4/4 Blogger par {kind.lower()} post kar raha hoon...")
    token = google_access_token()
    blog_id = (os.environ.get("BLOGGER_BLOG_ID") or "").strip()
    if not blog_id:
        raise AgentError("BLOGGER_BLOG_ID missing hai.")
    final_html = html_body.rstrip() + "\n" + sources_html(sources)
    post = blogger_create_post(token, blog_id, title, labels, final_html, as_draft)
    url = str(post.get("url", "")) or f"post id {post.get('id', 'unknown')}"
    print(f"      Ho gaya ({kind}): {title} -> {url}")
    return {"url": str(post.get("url", "")), "id": str(post.get("id", "")), "title": title}


def build_article(cfg: dict, focus: str, recent_titles: list[str], today: str) -> dict:
    """Steps 1-3: topic + draft + edit. Post nahi karta."""
    topic, angle = pick_topic(cfg, focus, recent_titles, today)
    draft_text, sources = write_article(cfg, topic, angle)
    title, labels, html_body = edit_article(cfg, draft_text)
    return {
        "topic": topic,
        "angle": angle,
        "title": title,
        "labels": labels,
        "body": html_body,
        "sources": sources,
    }


# --------------------------------------------------------------------------
# Slot logic
# --------------------------------------------------------------------------


def slot_datetime(slot: dict, day: datetime) -> datetime:
    hh, mm = slot["time"].split(":")
    return day.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


def attempt_count(state: dict, key: str) -> int:
    """Kitni baar try ho chuka hai (state.json haath se badla ho to bhi crash na kare)."""
    try:
        return int(state.get("attempts", {}).get(key, 0))
    except (TypeError, ValueError):
        return 0


def slot_decision(slot: dict, day: datetime, now: datetime, state: dict, key: str) -> tuple[bool, str]:
    """Ye slot abhi chalana hai ya nahi? Returns (run_karo, reason_in_hinglish)."""
    due_at = slot_datetime(slot, day)
    if key in state.get("done", {}):
        return False, "ye slot aaj already ho chuka hai"
    if now < due_at:
        return False, f"abhi time nahi hua (slot {slot['time']} IST)"
    if now - due_at > timedelta(hours=GRACE_HOURS):
        return False, f"{GRACE_HOURS} ghante ka grace window nikal gaya"
    if attempt_count(state, key) >= MAX_ATTEMPTS:
        return False, f"{MAX_ATTEMPTS} attempts ho chuke hain, ab nahi chalega"
    return True, "chalana hai"


def run_slot(cfg: dict, slot: dict, key: str, state: dict) -> dict:
    """Ek slot poora chala deta hai (4 steps + state update)."""
    now = now_ist()
    today = now.strftime("%Y-%m-%d")
    state["attempts"][key] = attempt_count(state, key) + 1
    save_state(state)  # attempt count turant save, taaki crash par bhi count sahi rahe

    article = build_article(cfg, slot["focus"], state.get("titles", []), today)
    post = publish(cfg, article["title"], article["labels"], article["body"], article["sources"])

    state["done"][key] = {"title": post["title"], "url": post["url"], "at": now.strftime("%Y-%m-%d %H:%M")}
    state["titles"].append(post["title"])
    state["titles"] = state["titles"][-MAX_TITLES:]
    save_state(state)
    return post


# --------------------------------------------------------------------------
# Test modes
# --------------------------------------------------------------------------


def run_check() -> int:
    """--check: env vars + chhota Groq call + Blogger blog name. Koi post nahi."""
    print("=== CHECK: setup sahi hai ya nahi ===")
    all_ok = True

    print("\n[1] Environment variables (.env ya Actions Secrets)")
    for name in REQUIRED_ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            print(f"  OK     {name}")
        else:
            print(f"  MISSING {name}")
            all_ok = False

    print("\n[2] Groq API test (ek chhota sa call)")
    if (os.environ.get("GROQ_API_KEY") or "").strip():
        try:
            # max_completion_tokens chhota rakhte hain kyunki reasoning tokens bhi usi me jaate hain.
            reply, _ = ask("Reply with the word OK only.", system="You reply with one word.",
                           use_search=False, max_tokens=300, temperature=0.1)
            print(f"  OK     Groq ne jawab diya: {reply.strip()[:60]!r} (edit model: {edit_model()})")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL   Groq call fail: {str(exc)[:300]}")
            all_ok = False
    else:
        print("  SKIP   GROQ_API_KEY missing hai, Groq call skip kiya.")
        all_ok = False

    print("\n[3] Blogger / Google OAuth test")
    google_ready = all((os.environ.get(name) or "").strip()
                       for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN",
                                    "BLOGGER_BLOG_ID"))
    if google_ready:
        try:
            token = google_access_token()
            blog = blogger_get_blog(token, (os.environ.get("BLOGGER_BLOG_ID") or "").strip())
            print(f"  OK     Blogger se connected. Blog: {blog.get('name', 'naam nahi mila')}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL   Blogger check fail: {str(exc)[:300]}")
            all_ok = False
    else:
        print("  SKIP   Google/BLOGGER keys missing hain, Blogger check skip kiya.")
        all_ok = False

    print("\n=== RESULT ===")
    if all_ok:
        print("SAHI: sab kuch theek hai. Ab --dry-run try karo.")
        return 0
    print("Kuch gadbad hai. Upar wale MISSING/FAIL lines padho aur .env ya GitHub Secrets fix karo.")
    return 1


def run_dry_run(cfg: dict, slot_index: int) -> int:
    """--dry-run: step 1-3 chala kar preview HTML file banata hai. Post nahi karta."""
    slot = cfg["slots"][slot_index]
    now = now_ist()
    today = now.strftime("%Y-%m-%d")
    print(f"=== DRY RUN (koi post nahi jayega) | slot {slot_index}: {slot['time']} IST | focus: {slot['focus']} ===")

    state = load_state()
    article = build_article(cfg, slot["focus"], state.get("titles", []), today)

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_path = PREVIEW_DIR / f"{now.strftime('%Y%m%d-%H%M%S')}.html"
    preview_path.write_text(
        preview_page(article["title"], article["labels"], article["body"], article["sources"]),
        encoding="utf-8",
    )
    print(f"\nPreview file bani: {preview_path}")
    print(f"Title: {article['title']}")
    print(f"Labels: {', '.join(article['labels']) or '(koi nahi)'}")
    print(f"Sources: {len(article['sources'])} asli URL mile")
    print("Browser me is file ko open karke article dekh lo. state.json chhua nahi gaya.")
    return 0


def run_now(cfg: dict, slot_index: int) -> int:
    """--now: chaaron steps chala kar post karta hai (config ke mode ke hisaab se)."""
    slot = cfg["slots"][slot_index]
    now = now_ist()
    today = now.strftime("%Y-%m-%d")
    print(f"=== NOW (post jayega) | slot {slot_index}: {slot['time']} IST | focus: {slot['focus']} ===")
    print(f"Mode: {cfg['mode']}")

    state = load_state()
    article = build_article(cfg, slot["focus"], state.get("titles", []), today)
    post = publish(cfg, article["title"], article["labels"], article["body"], article["sources"])
    print(f"\nPost URL: {post['url'] or '(draft me URL nahi mila)'}")
    print("Test mode hai, isliye state.json me kuch nahi likha gaya.")
    return 0


def run_scheduled(cfg: dict) -> int:
    """Normal scheduled run (koi flag nahi): aaj ke due slots chala deta hai."""
    if not cfg.get("enabled", True):
        print("config.json me enabled = false hai, agent abhi kuch nahi karega. (Chalane ke liye true kar do.)")
        return 0

    now = now_ist()
    today = now.strftime("%Y-%m-%d")
    print(f"=== BLOG AGENT | {now.strftime('%Y-%m-%d %H:%M')} IST | mode: {cfg['mode']} ===")

    state = load_state()
    ran = 0

    for index, slot in enumerate(cfg["slots"]):
        key = f"{today} {slot['time']}"
        should_run, reason = slot_decision(slot, now, now, state, key)
        if not should_run:
            print(f"- Slot {slot['time']} IST ({slot['focus']}): skip - {reason}")
            continue

        print(f"\n>>> Slot {index + 1}/{len(cfg['slots'])}: {slot['time']} IST | focus: {slot['focus']}")
        try:
            run_slot(cfg, slot, key, state)
            ran += 1
        except Exception as exc:  # noqa: BLE001 - ek slot fail ho jaye to agla slot bhi chale
            print(f"- Slot {slot['time']} IST fail hua: {str(exc)[:300]} ( agli run me retry hoga)", file=sys.stderr)

    if ran:
        print(f"\n{ran} slot(s) post ho gaye. state.json save kar diya gaya hai.")
    else:
        print("\nKoi naya slot chalane layak nahi tha. (Kuch nahi kiya, bilkul normal hai.)")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def pick_slot(cfg: dict, index: int) -> int:
    total = len(cfg["slots"])
    if index < 0 or index >= total:
        raise AgentError(
            f"--slot {index} galat hai. config.json me sirf {total} slot hain "
            f"(0 se {total - 1} tak chalega)."
        )
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Autonomous blogging agent (Groq research + Blogger posting). "
                    "Koi flag na de to scheduled mode chalta hai aur config.json ke due slots post karta hai.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="sab kuch check karo (env vars, Groq call, Blogger blog). Koi post nahi.")
    mode.add_argument("--dry-run", action="store_true",
                      help="slot chala kar article banao aur preview/ me HTML file banao. Post nahi.")
    mode.add_argument("--now", action="store_true",
                      help="ek post abhi bana do (config ke mode ke hisaab se draft/publish).")
    parser.add_argument("--slot", type=int, default=0,
                        help="test mode me config.json ka kaunsa slot use karna hai (default: 0)")
    args = parser.parse_args(argv)

    load_env()

    if args.check:
        return run_check()

    try:
        cfg = load_config()
        slot_index = pick_slot(cfg, args.slot)
    except AgentError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    try:
        if args.dry_run:
            return run_dry_run(cfg, slot_index)
        if args.now:
            return run_now(cfg, slot_index)
        return run_scheduled(cfg)
    except AgentError as exc:
        print(f"[ERROR] {str(exc)[:300]}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - user ko traceback nahi, saaf message chahiye
        print(f"[ERROR] Kuch galat ho gaya: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nUser ne Ctrl+C daba diya. Bye!", file=sys.stderr)
        sys.exit(130)