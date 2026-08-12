"""CALL 2, part 1 — what kind of page is this, and what does each block say
about itself.

OWNS STEPS 1-2 (with sub-steps 2a, 2b, 2c) — see prompts/__init__.py for the map.

Classification, then the block headers: the event number, discipline, gender,
age group, phase and date that every row underneath them inherits. Nothing here
reads a swimmer.

Debugging: STEP 2c is the one that matters. The record line sits between the
block heading and the first result and looks exactly like a competitor — a name,
a time, a country code and a date. Emitted as a row it invents a swimmer; read
as the header date it back-dates the whole block by two years.
"""

PAGE_STEPS = """\
You are reading a page of SWIMMING results, printed by meet-management software
(Splash Meet Manager, Hy-Tek Meet Manager, or similar).

STEP 1 — Classify the page. Set page_type to exactly one of:

  "result_list"  the page shows finishing places with TIMES — numbered entries,
                 each with a swimmer or team name and a finishing time
  "other"        anything else — a cover page, a session schedule, a start list
                 or heat sheet (entries and lane draws but NO times), a psych
                 sheet, a medal tally, a rulebook page, prose

The test is TIMES ACHIEVED. A page listing who is due to swim in which lane is a
start list, not a result: classify it "other".

If "other": nulls everywhere and an empty `blocks` array. Stop.
Otherwise extract EVERY entry the page shows. Do not return an empty array for a
page you have classified "result_list".

STEP 2 — The page is a STACK OF EVENT BLOCKS, and `blocks` gets one entry per
block, top to bottom. Read each block's heading before its rows.

A full block heading is three lines:

    Event 1                    Men, 200m Freestyle                     Open
    29-01-2025                                              Results Prelim
    NATIONAL GAMES  1:49.09  Srihari Nataraj      IND  GOA       29-10-2023

Take from it:

  event_no    = the number in "Event 1"                             -> 1
  gender      = the word before the comma                           -> "Men"
  discipline  = what follows that comma, the race itself            -> "200m Freestyle"
  age_group   = the category at the RIGHT-HAND END of the first line -> "Open"
  date_raw    = the date at the left of the second line             -> "29-01-2025"
  phase       = the word after "Results" on the second line         -> "Prelim"
  continued   = false

The gender word and the discipline are printed as one run of text, "Men, 200m
Freestyle". Split them at the comma. Keep the relay multiplier inside the
discipline: "4 x 100m Medley" is the discipline, not "100m Medley".

If the second line reads "Results" with no word after it, phase is null — that
is a timed final. Never invent "Final" to fill it.

STEP 2a — CONTINUATION BLOCKS. A block whose rows ran past the bottom of the
previous page restarts at the top of this one with a SINGLE comma-separated
line and no record line under it:

    Event 2, Women, 200m Freestyle, Prelim, Open

That line holds the same parts in a fixed order — event number, gender,
discipline, phase, age group. Split it on the commas and fill the same fields.
Set continued = true, and leave date_raw and date_iso NULL: a continuation block
prints no date, and the pipeline carries the date forward for you. Do NOT copy
the date of the block below it, and do NOT take one from the page footer.

Every block on the page gets its own heading values. A block NEVER inherits the
event number, discipline or phase of the block above or below it.

STEP 2b — Page-level fields. `event` is the MEET name: the largest heading at
the very top of the page, e.g. "38th NATIONAL GAMES 2025". It is the same on
every page of the document. It is NOT the name of a single race — "200m
Freestyle" is a discipline and belongs to a block, never to `event`.

The page-level date_raw / date_iso / date_source are the session date of the
FIRST block on the page that prints one. If no block on the page prints a date,
all three are null. date_source says where you found it in a few words.

date_iso is the 10 characters YYYY-MM-DD and nothing else. The dates on these
pages are printed day-first: "29-01-2025" is 2025-01-29, NOT 2025-29-01.

NEVER guess a date, and never take one from your own knowledge of when the meet
was held.

STEP 2c — THE RECORD LINE IS NOT A COMPETITOR. Read this twice.

The third line of a full block heading states the record this race was swum
against. It looks like a result — it has a name, a time, a country code and a
date — and it is the single most common thing to get wrong on these pages.

    NATIONAL GAMES  1:49.09  Srihari Nataraj      IND  GOA       29-10-2023
    ^label          ^mark    ^who holds it        ^     ^where   ^when, PAST

You can always tell it apart from a result, by all four of these at once:
  - it sits ABOVE the "Rank ... Time" column labels; results sit below them
  - it has no rank number
  - it starts with a record LABEL — NATIONAL GAMES, MEET RECORD, NR, WR, NMR
  - its date is years in the past, not the session date

Put it in the block's record_type / record_time / record_holder /
record_nation / record_place / record_date, as YYYY-MM-DD for the date.

It must NEVER appear as an entry in `results`. Its holder is usually swimming in
the race below it — that swimmer gets ONE row, from the ranked list, with the
time he swam today, not the record time. And the block's date_iso is the session
date on the line ABOVE the record line; never the record's own date.

If a block prints no record line, all six record fields are null.
"""
