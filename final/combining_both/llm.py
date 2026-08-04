"""Everything that talks to the OpenAI HTTP API."""
import base64
import hashlib
import json
import threading
from collections import defaultdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (BASE_URL, CACHE_DIR, HEADER_MODEL, HTTP_RETRIES,
                    JUDGE_MODEL, MAX_OUT, MAX_OUT_CEILING, MODEL, SHOW_TOKENS,
                    api_key)
from log import log
from prompts import HEADER_SCHEMA, JUDGE_PROMPT, PROMPT, SCHEMA, header_prompt

# Keyed "<call kind> (<model>)", filled from the API's own `usage` block, so
# these are billed numbers rather than an estimate.
USAGE = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cached": 0})
_usage_lock = threading.Lock()          # several pages report at once


def _record(label: str, model: str, usage: dict) -> None:
    if not usage:
        return
    got_in  = usage.get("prompt_tokens", 0)
    got_out = usage.get("completion_tokens", 0)
    cached  = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)

    with _usage_lock:
        t = USAGE[f"{label} ({model})"]
        t["calls"] += 1
        t["in"]    += got_in
        t["out"]   += got_out
        t["cached"] += cached

    if SHOW_TOKENS:
        note = f"  cached={cached:,}" if cached else ""
        log.info(f"    tokens · {label:<7} in={got_in:>7,}  out={got_out:>5,}  "
                 f"total={usage.get('total_tokens', got_in + got_out):>7,}{note}")


def usage_summary() -> str:
    """Per-call-kind totals for the whole run."""
    if not USAGE:
        return "  no LLM calls made"
    lines, tot_in, tot_out = [], 0, 0
    for name, t in USAGE.items():
        tot_in += t["in"]
        tot_out += t["out"]
        cached = f"  cached={t['cached']:>8,}" if t["cached"] else ""
        lines.append(f"  {name:<26} calls={t['calls']:>3}  "
                     f"in={t['in']:>9,}  out={t['out']:>7,}{cached}")
    lines.append(f"  {'TOTAL':<26} {'':>9}  in={tot_in:>9,}  out={tot_out:>7,}")
    return "\n".join(lines)


def _session() -> requests.Session:
    """One pooled session, retrying 429 and 5xx with exponential backoff — those
    arrive before the model generated anything, so replaying costs nothing.

    read=0 because a read timeout is the opposite case: the answer may have been
    generated and billed while we gave up waiting, and re-sending pays twice."""
    s = requests.Session()
    retry = Retry(total=HTTP_RETRIES, read=0, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"POST"}),
                  raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
    s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
    return s


SESSION = _session()


def _chat(payload: dict, timeout: int, label: str = "call") -> dict:
    r = SESSION.post(f"{BASE_URL}/chat/completions",
                     headers={"Authorization": f"Bearer {api_key()}",
                              "Content-Type": "application/json"},
                     json=payload, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    _record(label, payload["model"], body.get("usage"))
    return body


def _image_message(b64: str, text: str, detail: str) -> list:
    return [{
        "role": "user",
        "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}", "detail": detail}},
            {"type": "text", "text": text},
        ],
    }]


def page_png_b64(page, dpi: int) -> str:
    return base64.b64encode(page.get_pixmap(dpi=dpi).tobytes("png")).decode()


def _cache_path(b64: str, instructions: str, model: str):
    """Keyed by the three things that decide the answer, so a cached answer can
    never be one the current prompt would not have produced."""
    if not CACHE_DIR:
        return None
    key = hashlib.sha1(f"{model}\0{instructions}\0{b64}".encode()).hexdigest()
    return Path(CACHE_DIR) / f"{key}.json"


def extract_page(b64: str, note: str = "", page_no=None,
                 temperature: float = 0) -> dict:
    """Read one page.

    `note` is the audit's complaint about the previous answer, appended to the
    instructions on a re-read. `temperature` rises with the attempt number — see
    pipeline.retry_note. It is not part of the cache key and needs not be: it
    only ever moves in step with the note, which is.

    Answers are cached on disk, so editing a prompt re-pays only for the pages
    that edit actually changed."""
    instructions = PROMPT + note
    where = f"p{page_no}" if page_no else "page"

    cached = _cache_path(b64, instructions, MODEL)
    if cached and cached.exists():
        log.info(f"  {where}: served from cache ({cached.name[:8]})")
        return json.loads(cached.read_text())

    payload = {
        "model": MODEL,
        "temperature": temperature,
        "max_tokens": MAX_OUT,
        "messages": _image_message(b64, instructions, "high"),
        "response_format": SCHEMA,
    }
    body = _chat(payload, timeout=300, label="retry" if note else "extract")

    # Cut off mid-JSON: ask again once with more room, capped at the ceiling.
    # Doubling past the model's own output limit is a 400, which would turn a
    # merely truncated page into a failed one.
    if body["choices"][0].get("finish_reason") == "length":
        roomier = min(MAX_OUT * 2, MAX_OUT_CEILING)
        if roomier <= MAX_OUT:
            raise RuntimeError(f"output truncated at {MAX_OUT} tokens and "
                               f"OCR_MAX_OUT_CEILING ({MAX_OUT_CEILING}) leaves "
                               f"no room to ask again")
        log.warning(f"  ! {where}: output truncated at {MAX_OUT} tokens — "
                    f"asking again with {roomier}")
        payload["max_tokens"] = roomier
        body = _chat(payload, timeout=600, label="retry" if note else "extract")
        if body["choices"][0].get("finish_reason") == "length":
            raise RuntimeError(f"output still truncated at {roomier} tokens "
                               f"— raise OCR_MAX_OUT")

    out = body["choices"][0]["message"]["content"]
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(out)
    return json.loads(out)


def llm_headers(b64: str, samples: dict = None) -> list:
    """Name the CSV columns. Asked once per document, on a page already
    extracted, and given a few real values so it names columns after what they
    hold. Returns [(field, header)] in the order it wants them.

    Fails OPEN: [] on any error, and the caller falls back to the field names."""
    payload = {
        "model": HEADER_MODEL,
        "temperature": 0,
        "max_tokens": 700,
        "messages": _image_message(b64, header_prompt(samples or {}), "high"),
        "response_format": HEADER_SCHEMA,
    }
    try:
        body = _chat(payload, timeout=120, label="header")
        cols = json.loads(body["choices"][0]["message"]["content"])["columns"]
        return [(c["field"], c["header"]) for c in cols]
    except Exception as e:
        log.warning(f"  ! header call failed ({e}) — using the internal field names")
        return []


def llm_judge(b64: str) -> tuple:
    """The page filter: is this page worth an extraction call? (keep, why).

    Fails OPEN — a broken judge must not be why a real draw sheet goes missing.
    Takes the rendered image, not the fitz page: rendering happens under the
    caller's lock."""
    payload = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 60,
        "messages": _image_message(b64, JUDGE_PROMPT, "high"),
        "response_format": {"type": "json_object"},
    }
    try:
        body = _chat(payload, timeout=90, label="judge")
        out = json.loads(body["choices"][0]["message"]["content"])
        return bool(out.get("worth_reading")), str(out.get("why", ""))[:60]
    except Exception as e:
        log.warning(f"  ! judge call failed ({e}) — passing page through")
        return True, "call failed"
