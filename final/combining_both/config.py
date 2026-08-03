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

# When the audit says a page does not add up, hand it that complaint and read the
# page again. How many extra attempts a failing page gets; 0 turns it off. Only
# failing pages pay, and an answer is kept only if it has fewer complaints than
# the best one so far, so a retry can never make a page worse.
RETRY_ON_AUDIT = 2

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
#   2. the judge   -> a cheap vision model reads every remaining page and says
#                     whether it is worth an extraction call
# No keyword or geometry guessing sits in front of the judge any more: the only
# thing that decides a page's fate is a model that has actually looked at it.
PREFILTER   = True             # off = extract every non-blank page, no judging
LLM_FILTER  = True             # off = keep every non-blank page without asking
JUDGE_MODEL = "gpt-4o-mini"
JUDGE_DPI   = 150              # the judge has to READ the page, not glance at it

SHOW_TOKENS = True             # print the API's own usage numbers per call


def api_key() -> str:
    """Read the key at call time so importing a module never explodes."""
    try:
        return os.environ["OPENAI_API_KEY"]
    except KeyError:
        raise RuntimeError("OPENAI_API_KEY is not set") from None
