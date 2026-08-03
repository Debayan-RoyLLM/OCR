"""Tunables and constants shared by the whole pipeline."""
import os

BASE_URL = "https://api.openai.com/v1"
MODEL    = "gpt-4o"          # see note on model choice below
DPI      = 220

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
HEADER_MODEL = "gpt-4o"        # one call per document; worth the good model

HINTS = ["draw sheet", "standings", "quarterfinal", "semifinal", "preliminaries"]
PREFILTER = True

# --- page triage --------------------------------------------------------------
# EVERY enabled gate must pass before the expensive extraction call is made.
# Free gates run first; a paid gate is only asked once the free ones agree.
VECTOR_TRIAGE = True           # gate 3: does the page look like a bracket/flow chart?
LLM_TRIAGE    = False          # gate 4: ask a small vision model. costs money.
TRIAGE_MODEL  = "gpt-4o-mini"  # only used when LLM_TRIAGE is on
TRIAGE_DPI    = 110            # thumbnail resolution for gate 4
MIN_STROKES   = 25             # horizontal+vertical line segments implying a tree
MIN_BOXES     = 6              # or this many real rectangles

# A page that fails any gate is not dropped outright — a cheap vision model reads
# it and has the final say. Set False to drop it for free instead.
SHOW_TOKENS = True             # print the API's own usage numbers per call
JUDGE_FALLBACK = True
JUDGE_MODEL    = "gpt-4o-mini"
JUDGE_DPI      = 150           # higher than TRIAGE_DPI: the judge must actually read


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    try:
        return os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise RuntimeError("OPENAI_API_KEY is not set") from None
