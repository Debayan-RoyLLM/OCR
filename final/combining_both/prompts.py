"""The extraction contract: response schema and the instructions that go with it."""
from config import FIELDS

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "draw_sheet",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string",
                              "enum": ["draw_sheet", "ranking_table", "other"],
                              "description": "What kind of page this is. 'other' means nothing to extract."},
                "event": {"type": ["string", "null"],
                          "description": "Tournament name, the largest heading at the top."},
                "division": {"type": ["string", "null"],
                             "description": "The page's weight/category line, e.g. 'Elite Women - 48 Kg (EW-48 kg)'. Null if the page stacks several categories — then each row carries its own."},
                "date_raw": {"type": ["string", "null"],
                             "description": "The date exactly as printed anywhere on the page — header, title, or footer. Not tidied."},
                "date_iso": {"type": ["string", "null"],
                             "description": "The same date as YYYY-MM-DD. Month-and-year only becomes the 1st of that month. Null if no date is printed."},
                "date_source": {"type": ["string", "null"],
                                "description": "Where the date was found, a few words: 'As of line', 'title', 'footer Report Created', etc."},
                "standings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "division": {"type": ["string", "null"],
                                         "description": "The weight class / event type THIS row sits under, copied from the nearest heading above it or from the row's own weight-category column. Null only if the page shows no category at all."},
                            "rank": {"type": ["integer", "null"],
                                     "description": "The digit printed BEFORE the period. Transcribe it; never renumber."},
                            "name_short": {"type": ["string", "null"],
                                           "description": "Text between the period and the '(' — exactly as printed."},
                            "country": {"type": ["string", "null"],
                                        "description": "The 3-letter code inside the parentheses."},
                            "medal": {"type": ["string", "null"],
                                      "description": "Gold, Silver, Bronze, or null."},
                            "name": {"type": ["string", "null"],
                                     "description": "Full name from the bracket's Name column matching this boxer. Null if no confident match."},
                            "previous_rank": {"type": ["string", "null"],
                                              "description": "Ranking tables only: the previous-rank column as printed, e.g. '14' or 'x'. Null on draw sheets."},
                            "points_total": {"type": ["number", "null"],
                                             "description": "Ranking tables only: the total/final points column. Null on draw sheets."},
                        },
                        "required": ["division", "rank", "name_short", "country",
                                     "medal", "name", "previous_rank", "points_total"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["page_type", "event", "division",
                         "date_raw", "date_iso", "date_source", "standings"],
            "additionalProperties": False,
        },
    },
}

PROMPT = """\
STEP 1 — Classify the page. Set page_type to exactly one of:

  "draw_sheet"    a tournament bracket / draw sheet, normally with a box
                  labelled "Standings:"
  "ranking_table" a printed ranking list: numbered rows of athletes, each with a
                  country code and usually points columns
  "other"         anything else — cover page, schedule, rulebook page, photo,
                  legend, prose

If "other": nulls everywhere and an empty standings array. Stop.
Otherwise extract EVERY competitor the page shows. Do not return an empty array
for a page you have classified as draw_sheet or ranking_table.

STEP 2 — Header. Read the tournament or publication name (largest text at top)
and the weight/category line. Copy each EXACTLY as printed. On a ranking table
the category heading — e.g. "WOMEN'S 50KG RANKINGS" — is the division.

STEP 2a — Division belongs to the ROW, not to the page. One page very often
holds SEVERAL weight classes stacked one under the other:

    Men's Elite 50Kg          <- heading
    Rank Name Seed NOC        <- column labels
    1  Jalilov Asilbek  UZB   <- these rows are 50Kg
    ...
    Men's Elite 55Kg          <- next heading
    1  Olimov Samandar  UZB   <- these rows are 55Kg

Give EVERY row its own `division`, copied EXACTLY from the nearest category
heading above it. A row must never inherit the heading of the block above or
below its own. Where each row instead has a weight-category CELL — a "Weight
Category" column printing "E-F-48Kg" — that cell is that row's division.

A page-wide label such as "Top 8", "Final Standings", "Results" or "Page 3 of 7"
is NOT a division: it says nothing about weight or category. Never use one.

Set the top-level `division` only when the WHOLE page is a single category —
otherwise leave it null; the rows carry it.

STEP 2b — Date. Search the WHOLE page, not only the header:
  - an "As of" / "as at" / "Date:" line
  - the title or subtitle, e.g. "World Boxing Rankings — July 2026"
  - a session or competition date near the top
  - the footer, e.g. "Report Created  MA. 3 FEB. 2026 21:49"
If several appear, prefer the competition or ranking date over a printing
timestamp, and say which one you used in date_source.

  date_raw    = the date EXACTLY as printed, including any day name, dot, or
                abbreviation. Do not tidy or reorder it.
  date_iso    = the same date as YYYY-MM-DD. Convert month names in ANY
                language: "3 FEB. 2026" -> "2026-02-03", "Julio 2026" -> 2026-07.
                If only month and year are printed, use the 1st of that month:
                "July 2026" -> "2026-07-01".
                Output nothing but the 10 characters YYYY-MM-DD.
  date_source = a few words saying where you found it.

If no date is printed anywhere on the page, all three are null. NEVER guess a
date, and never take one from your own knowledge of when the event happened.

STEP 3a — IF page_type is "draw_sheet":
Find the box labelled "Standings:". Extract ONLY the lines inside it. Ignore the
bracket tree, all bout scores (WP 5:0, RSC R1), every "Bye", the NOTES and LEGEND
sections, and the page footer.

Each standings line has this exact form:

    <rank> . <NAME> (<CCC>) <medal?>

  rank       = the digit before the period. TRANSCRIBE IT AS PRINTED.
  name_short = the text between the period and the opening parenthesis.
  country    = the 3 letters inside the parentheses.
  medal      = Gold / Silver / Bronze, or null if nothing follows.
  division   = the weight class this box belongs to — the sheet's own category
               line, or the row's Weight Category cell on a bout-results page.
  previous_rank, points_total = null.

CRITICAL — ranks tie and repeat. Two bronze medallists are BOTH printed "3." and
must BOTH be rank 3. Four fifth-place boxers are ALL "5." and must ALL be rank 5.
Do NOT convert repeated ranks into a 1,2,3,4,5 sequence. If you output an
unbroken 1,2,3,4,5 you have made an error — re-read the printed digits.

STEP 3b — IF page_type is "ranking_table":
Extract every athlete row in the table. Skip column headers, the category
heading itself, and page furniture.

A row typically reads:  <rank> <prev> <NAME> <CCC> <points> <points> <total>

  rank          = the leftmost number, as printed.
  division      = the category heading standing directly above this row's block.
  previous_rank = the next column exactly as printed — a number, or the literal
                  "x" for a new entry. Keep it as a string. If the table has no
                  previous-rank column at all, null — never put another column
                  (seed, code, result) here.
  name          = the athlete name with the country code removed.
  name_short    = the same athlete name.
  country       = the 3-letter code.
  points_total  = the LAST points column (the total), as a number.
  medal         = null.

Ranks on a ranking table normally DO run 1,2,3,4,5… — that is expected here and
is not an error. Transcribe what is printed either way.

CRITICAL — the 3-letter country code goes in `country` and NOWHERE ELSE. It must
never appear in name_short or name.

STEP 4 — draw sheets only: look up each boxer's full name in the bracket's
Team/Name column on the left and put it in `name`. The box abbreviates surnames:
"RANI M" is "RANI MANJU"; a single letter like "N" or "K" is the full single-word
surname such as "NITU" or "KUSUM". If you cannot match one confidently, return
null — do not guess.

Never invent a competitor who is not printed on the page.
"""

TRIAGE_PROMPT = (
    "Does this page contain a bracket tree, flow chart, graph, or other "
    "line-and-box diagram? Plain prose, a title page, a plain table, or a "
    "list of results is NOT a diagram. Reply with JSON only: "
    '{"has_figure": true} or {"has_figure": false}'
)

# Asked only when a page fails one of the gates. The gates guess from shape and
# keywords; the judge actually looks. Biased toward yes on purpose — a wrongly
# admitted page costs one call, a wrongly dropped one loses rows for good.
# Must stay in step with STEP 1 of PROMPT. If the judge admits a page type the
# extractor calls "other", you pay twice and get nothing back.
JUDGE_PROMPT = (
    "The cheap filters were unsure about this page. Decide whether it is worth "
    "reading in full.\n"
    "Answer true if the page shows EITHER a tournament draw sheet / bracket with "
    "a standings box, OR a ranking table of numbered athletes with country codes "
    "— even if faint, rotated, scanned, or only partly visible.\n"
    "Answer false if it is a cover page, a session schedule, a bout order list, "
    "a rulebook page, a legend, a photo, or plain prose.\n"
    "If you are genuinely unsure, answer true.\n"
    'Reply with JSON only: {"has_standings": true, "why": "<six words max>"}'
)

# --- CSV header ---------------------------------------------------------------
# Asked ONCE per document, on the first page that survives triage and yields
# rows. The model does not choose what is extracted — FIELDS is fixed by SCHEMA —
# only what each column is called in the CSV and in what order they sit. The
# answer is cached for the whole run so page 40 can never disagree with page 1.
HEADER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "csv_header",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "description": "Every field exactly once, in the order the "
                                   "columns should appear in the CSV.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": FIELDS,
                                      "description": "The internal field being named."},
                            "header": {"type": "string",
                                       "description": "The column heading to print for it."},
                        },
                        "required": ["field", "header"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["columns"],
            "additionalProperties": False,
        },
    },
}

HEADER_PROMPT = """\
A whole document is being turned into ONE CSV, and this page is a sample of it.
Every row will always carry these fourteen fields. Their MEANING is fixed — you
are only choosing what to call each one at the top of the CSV.

  field          what the value always is        keep this name unless...
  event          the tournament / publication name
  date           that date as YYYY-MM-DD
  division       the weight class or category the row belongs to  ("weight_class")
  page_type      "draw_sheet" or "ranking_table" — the kind of page it came from
  rank           the athlete's placing
  name           the athlete's full name         ("boxer", "athlete")
  name_short     the same athlete's name as abbreviated in the standings box
  country        the 3-letter country code       ("noc")
  medal          "Gold" / "Silver" / "Bronze", or empty
  previous_rank  the athlete's rank in the PREVIOUS edition of the ranking
  points_total   the athlete's total ranking points
  date_raw       that same date exactly as printed on the page
  date_source    where on the page the date was found
  _page          the PDF page number             ("page")

Return all fourteen, once each, ordered as they should read in the CSV:
identifying columns first, provenance and debugging columns (date_raw,
date_source, _page) last.

Rules — read them all before answering:
  - The default is to KEEP the field's own name. Rename only when this document
    genuinely uses a different word for the SAME thing (country -> "noc").
  - NEVER use a value off the page as a header. "world_boxing_cup_finals_2025"
    is a value of `event`; the header is "event". Same for dates and weights.
  - NEVER borrow a column label from this page for a field that means something
    else. A page showing "Winner / Result / Decision / Seed / Bout" does not make
    `medal` "winner", `previous_rank` "result", `points_total` "decision", or
    `name_short` "seed". If in doubt, keep the field's own name.
  - lowercase snake_case, ASCII, at most three words, under 25 characters.
  - Two columns must never get the same header.
  - Do not merge, drop, invent, or split fields.
"""


def header_prompt(samples: dict) -> str:
    """HEADER_PROMPT plus real values already pulled out of this document.

    Shown because the model kept naming fields after the columns it could SEE on
    the page — calling `name_short` "seed" because the page has a Seed column.
    Values it can read settle that: nobody calls "Bak Chorong" a seed."""
    if not samples:
        return HEADER_PROMPT

    lines = []
    for field, values in samples.items():
        shown = ", ".join(f'"{v}"' for v in values) if values else "(always empty)"
        lines.append(f"  {field:<14} {shown}")

    return HEADER_PROMPT + (
        "\nBefore you answer: here is what these fields ACTUALLY hold in this "
        "document.\nName each column after the values you see, not after a "
        "column label printed on the page.\n\n" + "\n".join(lines) + "\n")
