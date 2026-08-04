"""Tunables and constants shared by the whole pipeline.

Environment variables, all optional:
    OPENAI_API_KEY   required at call time
    OPENAI_BASE_URL  any OpenAI-compatible endpoint (/chat/completions, Bearer,
                     image_url parts, response_format json_schema)
    OCR_MODEL        OCR_JUDGE_MODEL, OCR_HEADER_MODEL — the last two default to
                     OCR_MODEL, so a one-model deployment sets only OCR_MODEL
    OCR_DPI          OCR_WORKERS, OCR_CACHE, OCR_MAX_OUT, OCR_MAX_OUT_CEILING
"""
import os

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL    = os.getenv("OCR_MODEL", "gpt-4o")
DPI      = int(os.getenv("OCR_DPI", "220"))

# --- the two tables -----------------------------------------------------------
# Internal field names. The extraction schema and every audit check are written
# against these; what they are CALLED in the CSV is decided by LLM_HEADERS.
FIELDS = ["event", "date", "division", "page_type", "rank", "name", "name_short",
          "country", "medal", "previous_rank", "points_total",
          "date_raw", "date_source", "_page"]

# Who boxed whom, one row per bout -> <output>_bouts.csv
BOUT_FIELDS = ["event", "date", "division", "round", "bout_no",
               "boxer_a", "country_a", "boxer_b", "country_b",
               "winner", "result", "date_raw", "date_source", "_page"]

# Named in one header call, so a shared field gets the same name in both files.
ALL_FIELDS = FIELDS + [f for f in BOUT_FIELDS if f not in FIELDS]

# --- columns ------------------------------------------------------------------
LLM_HEADERS  = True            # off = write the CSVs with the field names above
HEADER_MODEL = os.getenv("OCR_HEADER_MODEL", MODEL)   # one call per document

KEEP_UNCHOSEN = False          # write fields the model's layout page left out

# ...or write one anyway once this share of the finished rows hold a value. The
# layout comes from ONE page; this is what rescues a column that page didn't show.
FILL_BACK = 0.05

# Always written when they hold data, whatever the layout said: without these a
# row cannot be identified or traced back.
CORE_FIELDS = {"event", "date", "division", "_page",
               "rank", "name", "country",                    # standings
               "round", "boxer_a", "boxer_b", "winner", "result"}  # bouts

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
# an extraction, so it pays off once about a fifth of the pages are junk — on a
# PDF where nearly every page is a draw sheet, turn PREFILTER off.
PREFILTER   = True             # off = extract every non-blank page, no judging
JUDGE_MODEL = os.getenv("OCR_JUDGE_MODEL", MODEL)
JUDGE_DPI   = 150              # the judge has to READ the page, not glance at it

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


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    try:
        return os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise RuntimeError("OPENAI_API_KEY is not set") from None
