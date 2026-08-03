"""Tunables and constants shared by the whole pipeline."""
import os

BASE_URL = "https://api.openai.com/v1"
MODEL    = "gpt-4o"          # see note on model choice below
DPI      = 220

## for csv
COLS = ["event", "date", "division", "rank", "name", "name_short",
        "country", "medal", "date_raw", "_page"]

HINTS = ["draw sheet", "standings", "quarterfinal", "semifinal", "preliminaries"]
PREFILTER = True

# --- page triage ladder (cheapest first) -------------------------------------
# 1. keywords (free)  2. vector geometry (free)  3. mini vision model (cheap)
VECTOR_TRIAGE = True           # stage 2: does the page look like a bracket/flow chart?
LLM_TRIAGE    = False          # stage 3: ask a small vision model. costs money.
TRIAGE_MODEL  = "gpt-4o-mini"  # only used when LLM_TRIAGE is on
TRIAGE_DPI    = 110            # thumbnail resolution for stage 3
MIN_STROKES   = 25             # horizontal+vertical line segments implying a tree
MIN_BOXES     = 6              # or this many real rectangles


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    try:
        return os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise RuntimeError("OPENAI_API_KEY is not set") from None
