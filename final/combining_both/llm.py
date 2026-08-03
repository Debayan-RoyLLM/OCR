"""Everything that talks to the OpenAI HTTP API."""
import base64
import json
from collections import defaultdict

import requests

from config import (BASE_URL, HEADER_MODEL, JUDGE_DPI, JUDGE_MODEL, MODEL,
                    SHOW_TOKENS, api_key)
from prompts import HEADER_SCHEMA, JUDGE_PROMPT, PROMPT, SCHEMA, header_prompt

# Running tally, keyed by "<call kind> (<model>)". Filled from the `usage` block
# the API returns — these are the real billed numbers, not an estimate.
USAGE = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cached": 0})


def _record(label: str, model: str, usage: dict) -> None:
    if not usage:
        return
    t = USAGE[f"{label} ({model})"]
    got_in  = usage.get("prompt_tokens", 0)
    got_out = usage.get("completion_tokens", 0)
    cached  = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)

    t["calls"] += 1
    t["in"]    += got_in
    t["out"]   += got_out
    t["cached"] += cached

    if SHOW_TOKENS:
        note = f"  cached={cached:,}" if cached else ""
        print(f"    tokens · {label:<7} in={got_in:>7,}  out={got_out:>5,}  "
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


def _chat(payload: dict, timeout: int, label: str = "call") -> dict:
    r = requests.post(f"{BASE_URL}/chat/completions",
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


def extract_page(b64: str, note: str = "") -> dict:
    """Read one page. `note` is appended to the instructions on a second attempt:
    the audit's own complaint about the first answer, told back to the model."""
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 8000,        # a full bracket is a lot of bouts on top of the standings
        "messages": _image_message(b64, PROMPT + note, "high"),
        "response_format": SCHEMA,
    }
    body = _chat(payload, timeout=300, label="retry" if note else "extract")
    if body["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("output truncated — raise max_tokens")
    return json.loads(body["choices"][0]["message"]["content"])


def llm_headers(b64: str, samples: dict = None) -> list:
    """Asked once per document, on a page we have already rendered and extracted.
    Gets that page's image AND a few values already pulled off it, so it names
    the columns after what they hold. Returns [(field, header)] in the order it
    wants them. Fails OPEN: on any error return [], and the caller falls back to
    the internal field names rather than losing the run's output."""
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
        print(f"  ! header call failed ({e}) — using the internal field names")
        return []


def llm_judge(page) -> tuple:
    """The page filter. Reads every non-blank page and says whether it is worth
    an extraction call. Returns (keep, why). Fails OPEN — a broken judge must
    never be the reason a real draw sheet goes missing."""
    payload = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 60,
        "messages": _image_message(page_png_b64(page, JUDGE_DPI), JUDGE_PROMPT, "high"),
        "response_format": {"type": "json_object"},
    }
    try:
        body = _chat(payload, timeout=90, label="judge")
        out = json.loads(body["choices"][0]["message"]["content"])
        return bool(out.get("has_standings")), str(out.get("why", ""))[:60]
    except Exception as e:
        print(f"  ! judge call failed ({e}) — passing page through")
        return True, "call failed"
