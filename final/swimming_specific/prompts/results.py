"""CALL 2, part 2 — where each swimmer FINISHED. Fills each block's `results`.

OWNS STEP 3 (with sub-steps 3a-3d) — see prompts/__init__.py for the map.

Debugging: the four failures this text prevents, each of which audit.py also
checks for —
  * the second row of a TIE losing its rank, because the page prints it blank
  * DNS / DSQ rows getting a rank invented for them
  * the team landing nowhere, because its column is LABELLED "YB"
  * a DSQ reason or an NMR flag becoming a row of its own
"""

RESULTS_STEPS = """\
STEP 3 — `results`: every entry printed under the block's column labels.

The column labels are the line reading "Rank ... YB ... Time". Everything below
it and above the next "Event N" heading belongs to this block. A typical row:

    Rank                       YB                        Time
      1.  Srihari Nataraj           Karnataka         1:54.80      Q
      ^   ^name                     ^team             ^time_raw    ^status

  rank      = the digit before the period, TRANSCRIBED AS PRINTED
  name      = the swimmer's name, exactly as printed
  team      = the value in the SECOND name column
  time_raw  = the finishing time exactly as printed, colon and all
  status    = the letter after the time, if any
  remark, record_set = null unless STEP 3c applies

STEP 3a — THE SECOND NAME COLUMN IS THE TEAM, whatever it is labelled.

That column is very often headed "YB" — year of birth — and holds no years at
all. It holds "Karnataka", "SSCB", "Andhra Pradesh": the state, unit or club the
swimmer represents. Put that value in `team`.

Trust the VALUES, not the label. A column of place names is a team column even
when the heading says YB, Age, or nothing at all. Only if the column genuinely
holds four-digit years does it hold years — and then leave `team` null rather
than putting a year in it.

`team` is not a 3-letter code here and need not be one. "Goa", "SSCB", "Uttar
Pradesh" are all teams. Copy what is printed.

STEP 3b — TIES: A RANK PRINTED ONCE COVERS BOTH ROWS.

When two swimmers dead-heat, the page prints the rank on the first of them and
leaves the rank column BLANK on the second:

     15.   Shubrant Patra        Odisha          2:05.43
           Unni Krishnan S       SSCB            2:05.43     <- blank, same time
     17.   Raiyan Rajeeb         Delhi           2:07.18     <- numbering resumes at 17

A row with a blank rank and the SAME time as the row above it is tied with it:
give it that same rank. Both rows above are rank 15. The next number printed
skips ahead — 17, not 16 — and that skip is your confirmation that the tie was
real. Transcribe the 17; never renumber it to 16.

Do not confuse this with STEP 3c: a blank-rank line carrying a TIME is a tied
swimmer, a blank-rank line carrying no time is an annotation.

STEP 3c — ANNOTATION LINES BELONG TO THE ROW ABOVE, and are never rows.

Two things are printed on their own line beneath an entry:

  a record flag — "NMR", "NGR", "NR", "MR" — meaning THIS swim set a record.
    Set record_set = true on the row above it. Do not create a row for it, and
    do not confuse it with the record line of STEP 2c, which sits above the
    column labels and states the OLD record.

  a disqualification reason — "Early Start", "Crossed 15 mtr mark.",
    "Breast stroke kick during stroke". Put the text in `remark` on the row
    above it, exactly as printed.

Neither ever becomes an entry in `results`.

STEP 3d — STATUS CODES.

A code printed in the RANK column, where a number would be, means the swimmer
did not produce a ranked swim:

  DNS   did not start        DNF   did not finish
  DSQ   disqualified         WD    withdrawn        NS   no show

    DNS   Aman Raj            Bihar                            <- no time at all
    DSQ   Yatharth Singh Yadav  Uttar Pradesh     1:07.57      <- swam, then DSQ
          Early Start                                          <- its remark

For these: status = the code, and rank = NULL. Never give a DNS or a DSQ a rank,
and never renumber the ranked swimmers to close the gap they leave.
A DSQ often still has a time printed — keep it. A DNS has none — time_raw null.

A letter printed AFTER THE TIME is a qualifying mark, not a failure:

  Q   qualified for the final        R   reserve for the final

Those rows keep their rank and their time; status is just "Q" or "R". A row with
no letter after its time has status null — do not write "" or "-".

STEP 3e — RELAY BLOCKS: the entry is a TEAM, not a swimmer.

When the discipline reads "4 x 100m Freestyle", each ranked entry is a team:

     1. Tamilnadu                 Tamilnadu           3:39.17     Q
        Joshua Thomas, M.J.Praveen Kumar, M.S.Yadesh Babu, Benediction Rohit

The team name is printed twice, in the name column and again in the team column.
Put it in `team` BOTH times and leave `name` NULL — `name` is for individual
swimmers only. The indented line of four names is not part of this row; it is
STEP 4.

Every entry must be printed on the page. Never invent a swimmer, a team, a time
or a rank, and never carry an entry over from a block you read earlier.
"""
