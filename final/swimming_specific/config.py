"""Tunables and constants shared by the whole pipeline.

Environment variables, all optional:
    OPENAI_API_KEY   required at call time
    OPENAI_BASE_URL  any OpenAI-compatible endpoint (/chat/completions, Bearer,
                     image_url parts, response_format json_schema)
    OCR_MODEL        OCR_JUDGE_MODEL, OCR_HEADER_MODEL — the last two default to
                     OCR_MODEL, so a one-model deployment sets only OCR_MODEL
    OCR_DPI          OCR_WORKERS, OCR_CACHE, OCR_MAX_OUT, OCR_MAX_OUT_CEILING

They are the DEFAULTS the startup question offers; answering it overrides them
for that run only. See choose_provider at the bottom.
"""
import getpass
import os
import sys

import requests

OPENAI_URL = "https://api.openai.com/v1"

DPI = int(os.getenv("OCR_DPI", "220"))

# --- the two tables -----------------------------------------------------------
# Internal field names. The extraction schema and every audit check are written
# against these; what they are CALLED in the CSV is decided by LLM_HEADERS.
#
# One row per swimmer, or per TEAM on a relay -> <output>.csv
FIELDS = ["event", "event_no", "discipline", "gender", "phase",
          "date", "rank", "name", "team", "time_raw", "time_sec",
          "status", "date_raw", "date_source", "_page"]

# Who swam which leg, one row per relay swimmer -> <output>_relays.csv
RELAY_FIELDS = ["event", "event_no", "discipline", "gender", "phase", "date",
                "rank", "team", "leg", "swimmer", "status",
                "date_raw", "date_source", "_page"]

# Named in one header call, so a shared field gets the same name in both files.
ALL_FIELDS = FIELDS + [f for f in RELAY_FIELDS if f not in FIELDS]

# --- columns ------------------------------------------------------------------
LLM_HEADERS = True             # off = write the CSVs with the field names above

KEEP_UNCHOSEN = False          # write fields the model's layout page left out

# ...or write one anyway once this share of the finished rows hold a value.
#
# Only ever applied to a field the layout page did NOT show. The model names the
# columns off one page, so it can be ignorant of a field but it cannot be wrong
# about one it saw: if that page printed the field and the model still left it
# out, it decided the column does not belong and pipeline.finalize honours that.
# This share is what rescues the other case — `remark` on a document whose first
# page happens to have nothing disqualified on it.
FILL_BACK = 0.05

# Always written when they hold data, whatever the layout said: without these a
# row cannot be identified or traced back.
CORE_FIELDS = {"event", "event_no", "discipline", "date", "_page",
               "rank", "name", "team", "time_raw", "status",  # results
               "leg", "swimmer"}                              # relay legs

# --- retries ------------------------------------------------------------------
# Extra reads a page gets when the audit says it does not add up; 0 turns it off.
# An answer is kept only if it has fewer complaints than the best so far.
RETRY_ON_AUDIT = 3

# Re-reads step up in temperature. At 0 the model returns the identical wrong
# answer to the identical question, so the later attempts would be wasted.
RETRY_TEMP_STEP = 0.2
RETRY_TEMP_MAX  = 0.6

# --- page triage --------------------------------------------------------------
# Two filters: blank pages go free, then a vision model reads what is left and
# says whether it is worth an extraction call. The judge costs about a fifth of
# an extraction, so it pays off once about a fifth of the pages are junk.
#
# Off by default HERE because a meet-manager result PDF is result pages front to
# back — the judge would pass every one of them and bill for the privilege. Turn
# it back on for a mixed programme booklet with schedules and entry lists in it.
PREFILTER = False              # off = extract every non-blank page, no judging
JUDGE_DPI = 150                # the judge has to READ the page, not glance at it

# Why a page was kept or dropped. Constants because triage.py writes them and
# pipeline.py matches on them.
KEPT_NO_FILTER = "no filter"
KEPT_BY_JUDGE  = "judge"
DROP_BLANK     = "blank page"
DROP_BY_JUDGE  = "judge rejected"
TRIAGE_FAILED  = "triage failed"   # triage itself threw; the page is read anyway

# --- limits -------------------------------------------------------------------
SHOW_TOKENS = True             # print the API's own usage numbers per call

# Output cut off mid-JSON is asked again with twice the room, never past the
# ceiling — that is the model's own hard limit, and exceeding it is a 400.
MAX_OUT         = int(os.getenv("OCR_MAX_OUT", "8000"))
MAX_OUT_CEILING = int(os.getenv("OCR_MAX_OUT_CEILING", "16000"))

# Pages read at once. Output still prints in page order (see log.py).
# 1 = strictly serial, which is what you want when a page is misbehaving.
WORKERS = int(os.getenv("OCR_WORKERS", "4"))

HTTP_RETRIES = 3               # for 429 and 5xx; see llm._session

# Answers cached on disk, keyed by page image + prompt + model, so editing a
# prompt re-pays only for the pages it touched. OCR_CACHE="" turns it off.
CACHE_DIR = os.getenv("OCR_CACHE", ".ocr_cache") or None

# Where PDFs fetched from a link list are kept. They are kept rather than
# discarded so a stopped run resumes without re-downloading, and so the source
# of a page the audit flagged can still be opened. See fetch.py.
DOWNLOAD_DIR = os.getenv("OCR_DOWNLOADS", "downloads")


# --- which model, and where ---------------------------------------------------
# One dict rather than three constants because the answer arrives AFTER every
# module has been imported: llm.py asks for these through the functions below,
# so a choice made in main() still reaches the calls it makes.
#
# The environment fills it in first, which is what a cron or CI run gets — those
# have nobody to ask. A terminal is asked, and the environment's values become
# the defaults that Enter accepts.
def _root(url: str) -> str:
    """The part llm.py hangs a path off — everything up to and including /v1.

    A provider hands you the whole endpoint, "…/v1/chat/completions", and that
    is what gets pasted here. llm.py appends /chat/completions itself, so left
    alone it would POST to it twice and every call 404s. Trim it instead of
    refusing: both spellings mean the same endpoint."""
    url = (url or OPENAI_URL).strip().rstrip("/")
    for tail in ("/chat/completions", "/completions", "/responses"):
        if url.endswith(tail):
            return url[:-len(tail)]
    return url


_PROVIDER = {
    "base_url": _root(os.getenv("OPENAI_BASE_URL", "")),
    "api_key" : os.getenv("OPENAI_API_KEY", ""),
    "model"   : os.getenv("OCR_MODEL", "gpt-4o"),
}


def set_provider(base_url: str, key: str, model_name: str = "") -> None:
    """Point the run at an endpoint. Nothing is written to disk: a key typed at
    the prompt lives in this process and dies with it."""
    _PROVIDER["base_url"] = _root(base_url)
    _PROVIDER["api_key"]  = key
    if model_name:
        _PROVIDER["model"] = model_name


def base_url() -> str:
    return _PROVIDER["base_url"]


def model() -> str:
    return _PROVIDER["model"]


def header_model() -> str:
    """Named separately only if the environment says so; otherwise whatever the
    run is reading pages with — a one-model deployment needs no second name."""
    return os.getenv("OCR_HEADER_MODEL") or model()


def judge_model() -> str:
    return os.getenv("OCR_JUDGE_MODEL") or model()


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    if not _PROVIDER["api_key"]:
        raise RuntimeError("no API key — set OPENAI_API_KEY or answer the "
                           "prompt at startup")
    return _PROVIDER["api_key"]


def _masked(key: str) -> str:
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "the one already set"


def _ask(label: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    try:
        got = input(f"  {label}{shown}: ").strip()
    except EOFError:                      # stdin closed mid-question
        return default
    return got or default


def _ask_key(label: str, default: str = "") -> str:
    """getpass, so a key does not end up echoed on a shared screen or in a
    scrollback someone else reads."""
    shown = f" [{_masked(default)}]" if default else ""
    try:
        got = getpass.getpass(f"  {label}{shown} (hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nno key given") from None
    return got or default


def _probe(url: str, key: str, want: str) -> None:
    """Ask a custom endpoint what it serves.

    A wrong URL, a rejected key or a model name the server has never heard of
    all fail identically — as a 404 or 400 on the first page, after every PDF
    has already been fetched. One GET here turns that into a line you read
    before the run starts.

    Warning only, never fatal: plenty of gateways do not implement /models, and
    a missing directory is no reason to refuse to try."""
    try:
        r = requests.get(f"{url}/models", timeout=15,
                         headers={"Authorization": f"Bearer {key}"})
    except Exception as e:
        print(f"  ! could not reach {url} ({type(e).__name__}) — trying anyway")
        return

    if r.status_code == 401 or r.status_code == 403:
        print(f"  ! {url} rejected the key ({r.status_code})")
        return
    if r.status_code != 200:
        print(f"  ! {url}/models answered {r.status_code} — if the run fails, "
              f"the URL is the first thing to check")
        return

    try:
        names = [m.get("id", "") for m in (r.json().get("data") or [])]
    except ValueError:
        print(f"  ! {url}/models did not answer JSON — is this the API root?")
        return

    if names and want not in names:
        shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
        print(f"  ! this endpoint does not list {want!r}. It serves: {shown}")


def choose_provider() -> None:
    """Ask, once at startup, which endpoint this run should talk to.

    OpenAI needs a key and nothing else — the address is fixed. Anything else
    is 'custom': vLLM, Ollama, LM Studio, OpenRouter, a company gateway. They
    all speak the same POST /chat/completions with a Bearer header, so the only
    things that differ are the URL, the key and the model's name — and the name
    matters, because "gpt-4o" is not what a self-hosted server calls its model.

    Skipped without a terminal: a background run has no one to answer, and the
    environment variables decide there exactly as they did before."""
    if not sys.stdin.isatty():
        return

    print("\nWhich endpoint should this run use?")
    print("  1) OpenAI   — api.openai.com, API key only")
    print("  2) Custom   — any OpenAI-compatible endpoint: URL and API key")

    while True:
        choice = _ask("choice", "1").lower()
        if choice in ("1", "openai", "2", "custom"):
            break
        print("  ! answer 1 or 2")

    custom = choice in ("2", "custom")

    if custom:
        # An OpenAI key sitting in the environment is not this endpoint's key,
        # and the openai.com address is not its address, so neither is offered
        # as a default here.
        env_url = _PROVIDER["base_url"]
        url = ""
        while not url:
            url = _ask("base URL, ending at /v1 — e.g. http://localhost:8000/v1",
                       env_url if env_url != OPENAI_URL else "")
        key = ""
        while not key:
            key = _ask_key("API key")
        chosen_model = _ask("model name", _PROVIDER["model"])
    else:
        url, chosen_model = OPENAI_URL, _PROVIDER["model"]
        key = ""
        while not key:
            key = _ask_key("OpenAI API key", _PROVIDER["api_key"])

    set_provider(url, key, chosen_model)
    # The full target, not the answer as typed: if a pasted URL was trimmed
    # back to its root, this is where you see it.
    print(f"  → {model()} at {base_url()}/chat/completions")
    if custom:
        _probe(base_url(), key, model())
    print()
