"""Tunables and constants shared by the whole pipeline.

Anything you might want to change for one run without editing the file reads an
environment variable first: OCR_MODEL, OCR_DPI, OCR_WORKERS, OCR_CACHE.

To point the whole run at a different provider, set OPENAI_BASE_URL and
OPENAI_API_KEY. The endpoint must be OpenAI-compatible: /chat/completions,
a Bearer token, image_url content parts, and response_format json_schema.
The three model names are separate variables because a gateway rarely offers
the same ones OpenAI does — OCR_MODEL, OCR_JUDGE_MODEL, OCR_HEADER_MODEL.
"""
import os

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL    = os.getenv("OCR_MODEL", "gpt-4o")   # see note on model choice below
DPI      = int(os.getenv("OCR_DPI", "220"))

## for csv
# The pipeline's internal field names — fixed, because the extraction schema and
# every audit check are written against them. What they are CALLED in the CSV,
# and in what order, is decided once by the model (see LLM_HEADERS) on the first
# page that survives triage, then reused unchanged for every other page.
FIELDS = ["event", "date", "division", "page_type", "rank", "name", "name_short",
          "country", "medal", "previous_rank", "points_total",
          "date_raw", "date_source", "_page"]

# A draw sheet holds two different tables: who FINISHED where (FIELDS, above) and
# who BOXED WHOM to get there. One row per bout, written to <output>_bouts.csv.
BOUT_FIELDS = ["event", "date", "division", "round", "bout_no",
               "boxer_a", "country_a", "boxer_b", "country_b",
               "winner", "result", "date_raw", "date_source", "_page"]

# Both tables are named in one header call, so a field they share — event, date,
# division, _page — gets the same column name in both files.
ALL_FIELDS = FIELDS + [f for f in BOUT_FIELDS if f not in FIELDS]

LLM_HEADERS  = True            # off = write the CSVs with the field names above
HEADER_MODEL = os.getenv("OCR_HEADER_MODEL", MODEL)   # one call per document

# When the audit says a page does not add up, hand it that complaint and read the
# page again. How many extra attempts a failing page gets; 0 turns it off. Only
# failing pages pay, and an answer is kept only if it has fewer complaints than
# the best one so far, so a retry can never make a page worse.
RETRY_ON_AUDIT = 3

# The model picks the columns off the first real page and that stands for the
# whole document. A field it left out is not written even if later pages put
# something in it — the count is always printed. Set True to write them anyway.
KEEP_UNCHOSEN = False

# ...except these. Without them a row cannot be identified or traced, so they are
# written whenever they hold data, whatever the model decided. Everything outside
# this set — medal, name_short, previous_rank, points_total, bout_no, page_type,
# date_raw, date_source — is the model's call.
CORE_FIELDS = {"event", "date", "division", "_page",
               "rank", "name", "country",                    # standings
               "round", "boxer_a", "boxer_b", "winner", "result"}  # bouts

# --- page triage --------------------------------------------------------------
# Two filters, in this order:
#   1. blank page  -> discarded where it stands, nothing paid
#   2. the judge   -> a vision model reads every remaining page and says whether
#                     it is worth an extraction call
# No keyword or geometry guessing sits in front of the judge any more: the only
# thing that decides a page's fate is a model that has actually looked at it.
#
# The judge defaults to the SAME model as extraction, so a deployment serving one
# model needs only OCR_MODEL. It is cheap by SHAPE rather than by model — a
# smaller image, a ten-line prompt and 60 tokens of output, against a full page
# at 220 dpi and thousands of tokens either way. Roughly a fifth of an extraction
# call, so it pays for itself once about a fifth of the pages are junk. On a PDF
# where nearly every page is a draw sheet, set PREFILTER = False instead.
PREFILTER   = True             # off = extract every non-blank page, no judging
LLM_FILTER  = True             # off = keep every non-blank page without asking
JUDGE_MODEL = os.getenv("OCR_JUDGE_MODEL", MODEL)
JUDGE_DPI   = 150              # the judge has to READ the page, not glance at it

# The reason a page was kept or dropped. Constants because triage.py writes them
# and pipeline.py matches on them: as bare strings a typo in either file silently
# empties a line of the run summary instead of failing.
KEPT_NO_FILTER = "no filter"
KEPT_BY_JUDGE  = "judge"
DROP_BLANK     = "blank page"
DROP_BY_JUDGE  = "judge rejected"
TRIAGE_FAILED  = "triage failed"   # the filters themselves threw; the page is
                                   # kept and read anyway rather than silently lost

SHOW_TOKENS = True             # print the API's own usage numbers per call

# --- how hard to push ---------------------------------------------------------
# Pages are independent and every call is spent waiting on the network, so they
# are read several at a time. Output is still printed in page order (see log.py).
# 1 = strictly serial, which is what you want when a page is misbehaving.
WORKERS = int(os.getenv("OCR_WORKERS", "4"))

# Transient API failures — 429 and the 5xx family — are retried inside the HTTP
# layer before the page is ever declared failed.
HTTP_RETRIES = 3

# Extraction answers are cached on disk, keyed by the page image AND the prompt
# AND the model. Editing a prompt therefore invalidates it exactly where it
# should, and re-running a document after a prompt tweak costs nothing for the
# pages that tweak did not touch. Set OCR_CACHE="" to turn it off.
CACHE_DIR = os.getenv("OCR_CACHE", ".ocr_cache") or None


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    try:
        return os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise RuntimeError("OPENAI_API_KEY is not set") from None
