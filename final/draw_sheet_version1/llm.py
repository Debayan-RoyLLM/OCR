"""Everything that talks to the OpenAI HTTP API."""
import base64
import json

import requests

from config import (BASE_URL, MODEL, TRIAGE_DPI, TRIAGE_MODEL, api_key)
from prompts import PROMPT, SCHEMA, TRIAGE_PROMPT


def _chat(payload: dict, timeout: int) -> dict:
    r = requests.post(f"{BASE_URL}/chat/completions",
                      headers={"Authorization": f"Bearer {api_key()}",
                               "Content-Type": "application/json"},
                      json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


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


def extract_page(b64: str) -> dict:
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 4000,
        "messages": _image_message(b64, PROMPT, "high"),
        "response_format": SCHEMA,
    }
    body = _chat(payload, timeout=300)
    if body["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("output truncated — raise max_tokens")
    return json.loads(body["choices"][0]["message"]["content"])


def llm_has_figure(page) -> bool:
    """Stage 3 — one cheap low-detail vision call, bounded boolean answer.
    Fails OPEN: if the call errors, let the page through rather than drop it."""
    payload = {
        "model": TRIAGE_MODEL,
        "temperature": 0,
        "max_tokens": 16,
        "messages": _image_message(page_png_b64(page, TRIAGE_DPI), TRIAGE_PROMPT, "low"),
        "response_format": {"type": "json_object"},
    }
    try:
        body = _chat(payload, timeout=60)
        return bool(json.loads(
            body["choices"][0]["message"]["content"]).get("has_figure"))
    except Exception as e:
        print(f"  ! triage call failed ({e}) — passing page through")
        return True
