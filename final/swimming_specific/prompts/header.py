"""CALL 3 — naming the CSV columns.

Asked ONCE per document, on the first page that survives the filter and yields
rows, and cached for the whole run so page 40 can never disagree with page 1.

The model does not choose what is extracted — schema.py fixes that. It chooses
which fields become columns, what each is called, and in what order.
pipeline.finalize() then checks that choice against the finished data.
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
A whole document of SWIMMING RESULTS is being turned into TWO CSVs, and this page
is a sample of it. One file has a row per swimmer's PLACING, the other a row per
RELAY LEG. Their fields are below; the MEANING of each is fixed — you are only
choosing what to call it at the top of the file. Fields the two files share are
named once and used in both.

  field          what the value always is        keep this name unless...
  event          the MEET's name — "38th National Games 2025"     ("meet")
  event_no       the number in the "Event N" heading of the race
  discipline     the race itself — "200m Freestyle", "4 x 100m Medley"
  gender         "Men" / "Women" / "Mixed"       ("sex")
  age_group      the category — "Open", "Group I", "15-17 Yrs"    ("category")
  phase          "Prelim" / "Final" / "Semifinal", or empty       ("round")
  date           the session date as YYYY-MM-DD
  rank           the swimmer's or team's finishing place          ("place", "pos")
  name           the swimmer's full name         ("swimmer", "athlete")
  team           the state, unit or club swum for ("state", "club", "unit")
  time_raw       the finishing time as printed — "1:54.80"        ("time")
  time_sec       that same time in seconds — 114.80
  status         "Q", "R", "DNS", "DSQ", "DNF", or empty
  remark         a disqualification reason — "Early Start"        ("reason")
  record_set     true when THIS swim set a record (NMR was printed under it)
  leg            which leg of the relay the swimmer swam — 1 to 4
  swimmer        the name of the swimmer who swam that leg
  date_raw       that same date exactly as printed on the page
  date_source    where on the page the date was found
  _page          the PDF page number             ("page")

CHOOSE THE COLUMNS. Return only the fields that BELONG in this document's CSV —
every field you leave out gets no column at all, so leaving one out is a real
decision and not a formality. Judge it from what is on this page, because this
page is what the rest of the document looks like.

Leave a field out when the page shows it is never filled:

  - no Q / R / DNS anywhere on the page    -> leave out status
  - nothing disqualified, no reasons
    printed                                -> leave out remark
  - no record flag (NMR) under any swim    -> leave out record_set
  - the page shows only individual events,
    no relays                              -> leave out leg, swimmer
  - nothing on the page is dated           -> leave out date, date_raw, date_source

Leave a field out ALSO when it is filled but tells a reader of this file nothing
they came for. date_raw and date_source only exist so a suspect date can be
traced back to the page — keep them when the dates on this page are printed
oddly enough to be worth checking, drop them when the page dates plainly and
`date` on its own is the whole answer.

But keep a field that is filled and does say something, even if it says the same
thing on every row: one age group throughout is still a fact about these
results. A blank column is clutter and a redundant one is noise, but a field
this page clearly fills and a reader would want is lost data if you drop it —
that is the worse mistake of the two.

Always keep _page, so any row can be traced back to the page it came from.

Order what you keep as it should read: what identifies the race first
(event_no, discipline, gender), then the placing (rank, name, team, time), then
provenance last. Keep time_raw and time_sec adjacent and obviously the same
measurement.

Rules — read them all before answering:
  - The default is to KEEP the field's own name. Rename only when this document
    genuinely uses a different word for the SAME thing (team -> "state").
  - NEVER use a value off the page as a header. "38th_national_games_2025" is a
    value of `event`; the header is "event". Same for dates and disciplines —
    "200m_freestyle" is a value of `discipline`.
  - NEVER borrow a column label from this page for a field that means something
    else. These pages label the team column "YB" — year of birth — and print
    states in it. That does not make `team` "yb". A page showing "Rank / YB /
    Time" does not make `age_group` "yb" or `time_sec` "time" either. If in
    doubt, keep the field's own name.
  - lowercase snake_case, ASCII, at most three words, under 25 characters.
  - Two columns must never get the same header.
  - Do not merge, drop, invent, or split fields.
"""


def header_prompt(samples: dict) -> str:
    """HEADER_PROMPT plus real values pulled out of this document, so the model
    names a field after what it HOLDS rather than after a label printed nearby —
    nobody calls "Karnataka" a year of birth."""
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
