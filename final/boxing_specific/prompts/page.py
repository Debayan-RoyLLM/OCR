"""CALL 2, part 1 — what kind of page is this, and what does it say about itself.

OWNS STEPS 1-2 (with sub-steps 2a, 2b) — see prompts/__init__.py for the map.

Classification, then the three things every row on the page shares: event,
division, date. Nothing here reads a competitor.

Debugging: STEP 2a is where a page stacking a dozen weight classes gets its
per-row division. Wrong there and every row of the CSV inherits one label.
"""

PAGE_STEPS = """\
STEP 1 — Classify the page. Set page_type to exactly one of:

  "draw_sheet"    a tournament bracket / draw sheet, normally with a box
                  labelled "Standings:"
  "ranking_table" a printed ranking list: numbered rows of athletes, each with a
                  country code and usually points columns
  "other"         anything else — cover page, schedule, rulebook page, photo,
                  legend, prose

If "other": nulls everywhere, empty standings, empty bouts. Stop.
Otherwise extract EVERY competitor the page shows. Do not return an empty array
for a page you have classified as draw_sheet or ranking_table.

You are filling in TWO tables from this page, not one:
  standings — where each boxer FINISHED       (STEP 3)
  bouts     — who boxed whom on the way there (STEP 5)
A draw sheet gives you both. Fill in whichever the page actually shows.

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
"""
