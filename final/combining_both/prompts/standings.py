"""CALL 2, part 2 — where each boxer FINISHED. Fills the `standings` array.

Steps 3 and 4: the Standings box on a draw sheet, the rows of a ranking table,
and expanding the abbreviated names against the entry list.

Debugging note: the two failures this text exists to prevent are ranks losing
their ties (two bronzes are BOTH "3.") and the country code landing in a name
column. audit.py checks for both.
"""

STANDINGS_STEPS = """\
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
  previous_rank = the athlete's place in the PREVIOUS edition of this ranking,
                  printed in its own column — a number, or the literal "x" for a
                  new entry. Keep it as a string.
                  Most tables do not have this column. A table headed simply
                  "Rank | Name | Seed | NOC" has none: previous_rank is null for
                  every row. Never fill it with the Seed, the NOC, or a copy of
                  `rank` — if previous_rank equals rank on row after row, you are
                  copying the wrong column and it should have been null.
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
