"""CALL 2, part 3 — who boxed WHOM. Fills the `bouts` array.

Step 5: reading the chart itself rather than its summary box, plus the
bout-results table that carries the same information as rows.

This is the hardest part of the whole pipeline and the part most worth editing
in isolation. Three failure modes have all been seen for real, and each rule
below exists because of one of them:

  * rounds shifted by one column, because a first column padded with byes did
    not look like a round        -> "count BACKWARDS, from the right"
  * a pair read across two boxes, giving a winner who was in neither
                                 -> "enclosed together in their own drawn BOX"
  * a whole column silently dropped
                                 -> the frame arithmetic under CHECK YOUR WORK

audit.py re-runs that same arithmetic on the answer, so a page that still comes
up short is flagged rather than written out quietly.
"""

BRACKET_STEPS = """\
STEP 5 — `bouts`: read the CHART, not the Standings box.

IF the page is titled "Draw Sheet" or draws a bracket tree, work through the
tree itself and record EVERY bout in it — this is the point of the page and the
Standings box is only its summary.

How a bracket is drawn. Headings run across the top naming the columns, left to
right, in the order they were boxed. Read them off the page and list them in
`rounds_printed` exactly as written, whatever the words are:

    Preliminaries    Quarterfinals    Semifinals    Final
    Round of 16      1/4 Finals       1/2 Finals    Final
    Qualification    Last 16          Semi-Final    Gold Bout

The FIRST column is the entry list — Team | Name | Seed — every boxer who
started. Each later column holds only the boxers who WON in the column before
it, and printed under each of those names is the verdict that won it.

WHICH COLUMN IS WHICH ROUND — count BACKWARDS, from the right.
The right-hand edge of a bracket is never ambiguous: the last column is one
bout. The left edge is, because byes pad it out. So work right to left:

    the RIGHTMOST column  = the last heading   ->  1 pair
    the one before it     = second-to-last     ->  2 pairs
    the one before that                        ->  4 pairs
    ...doubling every step you move left...
    the ENTRY LIST column = the FIRST heading  ->  half the frame

The leftmost column of names therefore ALWAYS carries the first heading printed,
no matter how much of it is "Bye". If the sheet prints four headings, its entry
list is Preliminaries — never Quarterfinals. Never start at the second heading
because the first column looked sparse.

So every bout is read from TWO columns at once:
  - the two names joined by a bracket in column N are the boxers who met;
  - the one name at that join in column N+1 is the winner, and the verdict
    printed under THAT name is how the bout ended.

  round     = the heading of column N, where the PAIR sits — NOT of column N+1
              where the winner is printed. A pair in the Quarterfinals column is
              a quarterfinal even though its winner appears under Semifinals.
  boxer_a   = the upper name of the pair.
  boxer_b   = the lower name of the pair.
  winner    = the name at the join in the next column.
  result    = the verdict under that winner, exactly: "WP 5:0", "RSC R1", "WO".
  bout_no   = null unless the sheet numbers its bouts.

Work column by column, left to right, and record EVERY pair in EVERY column.

In the entry-list column the two boxers of a pair are enclosed together in their
own drawn BOX — one name at the top of the box, the other at the bottom, with
white space between them. Those two met each other. NEVER pair the name at the
bottom of one box with the name at the top of the next box: they are in
different bouts.

Byes. "Bye" printed where a name should be means that boxer had nobody to box
that round. It is still a line on the chart and you must record it: boxer_a is
the boxer, boxer_b and country_b are null, winner is that same boxer, result is
"Bye", and round is the column the pair sits in — the FIRST column when the Bye
faces an entry-list name.

CHECK YOUR WORK before you answer. The sheet prints "Number of boxers: N", and
that fixes every count on the page.

A bracket is always drawn in a frame whose size is the next power of two at or
above N — 5 boxers in a frame of 8, 10 or 12 boxers in a frame of 16. The frame,
not N, is what you can see drawn. From it:

    lines in total  = frame - 1     (every line, bouts and byes alike)
    real bouts      = N - 1         (a name on BOTH sides)
    byes            = frame - N     (a name on one side only)

  "Number of boxers: 16" -> frame 16: 15 lines = 15 bouts + 0 byes
  "Number of boxers: 12" -> frame 16: 15 lines = 11 bouts + 4 byes
  "Number of boxers: 10" -> frame 16: 15 lines =  9 bouts + 6 byes
  "Number of boxers: 5"  -> frame  8:  7 lines =  4 bouts + 3 byes

Count what you have written against all three numbers. A bracket of 10 has 15
lines, not 7 — six of those lines are byes and they are still lines. Coming up
short means you skipped a column or paired two boxers who never met; re-read the
chart and fix it. Do not invent a bye, a bout or a round to make it balance.

Names in the tree are abbreviated ("LYNIV S", "LOPEZ DEL ARBOL M"). Expand each
to the full name from the entry list on the left, exactly as in STEP 4, and take
country_a / country_b from that list too. Use the abbreviation as printed only
when no entry matches it.

IF INSTEAD the page is a bout-results table — rows of No. / Bout / Weight
Category / Corner / Name / NOC / Winner / Result / Decision — each ROW is one
bout: boxer_a is the RED corner, boxer_b is the BLUE corner, bout_no is the Bout
number, division is the row's Weight Category, and round is null unless printed.
The Winner column prints a corner colour — put the NAME of that corner's boxer in
`winner`, not "Red" or "Blue". `result` is the Result and Decision read together,
e.g. "WP 5:0".

Every bout must name at least one real boxer. Never invent a bout, a round, or a
verdict that is not drawn on the page.
"""
