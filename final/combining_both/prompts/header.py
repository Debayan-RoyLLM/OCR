"""CALL 3 — naming the CSV columns.

Asked ONCE per document, on the first page that survives the filter and yields
rows, and cached for the whole run so page 40 can never disagree with page 1.

The model does not choose what is extracted — that is fixed by schema.py. It
chooses which of those fields become columns, what each is called, and in what
order they read. pipeline.finalize() then checks that choice against the
finished data and drops any column that turned out blank in every row.
"""
from config import ALL_FIELDS

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
                    "description": "Only the fields this document actually fills, "
                                   "each at most once, in the order the columns "
                                   "should appear in the CSV. Leave a field out "
                                   "entirely and it gets no column.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": ALL_FIELDS,
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
A whole document is being turned into TWO CSVs, and this page is a sample of it.
One file has a row per athlete's PLACING, the other a row per BOUT. Their fields
are below; the MEANING of each is fixed — you are only choosing what to call it
at the top of the file. Fields the two files share are named once and used in
both.

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
  round          the stage a bout was fought at — "Semifinals", "Final"
  bout_no        the bout's number on the page
  boxer_a        the boxer in the top half of the bout, or the red corner
  country_a      boxer_a's 3-letter country code
  boxer_b        the boxer in the bottom half of the bout, or the blue corner
  country_b      boxer_b's 3-letter country code
  winner         the name of the boxer who won that bout
  result         how it was won — "WP 5:0", "RSC R1", "Bye"
  date_raw       that same date exactly as printed on the page
  date_source    where on the page the date was found
  _page          the PDF page number             ("page")

CHOOSE THE COLUMNS. Return only the fields this document actually fills — every
field you leave out gets no column at all. Judge it from what is on this page,
because this page is what the rest of the document looks like:

  - no points column printed anywhere      -> leave out points_total
  - no previous-rank column                -> leave out previous_rank
  - nothing on the page is dated           -> leave out date, date_raw, date_source
  - no medals awarded, only placings       -> leave out medal
  - the page draws no bracket and lists no
    bouts                                  -> leave out round, bout_no, boxer_a,
                                              country_a, boxer_b, country_b,
                                              winner, result
  - names are printed in full, never
    abbreviated in a standings box         -> leave out name_short

A column that would be blank in every single row is not worth printing. Equally,
do not leave out a field this page clearly fills — an empty column is clutter,
but a missing one is lost data.

Always keep _page, so any row can be traced back to the page it came from.

Order what you keep as it should read: identifying columns first, provenance
last. Keep the a/b pairing obvious — whatever you call boxer_a and country_a,
name boxer_b and country_b to match.

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
