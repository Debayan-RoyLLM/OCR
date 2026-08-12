"""CALL 2, part 3 — who swam which leg. Fills each block's `relay_legs`.

OWNS STEP 4, the last one — see prompts/__init__.py for the map.

A relay entry is one row in `results` (the team, its rank and its time) and four
rows here (the swimmers, in swum order). Two tables rather than four more columns
on the first, because an individual event would leave all four blank.

Debugging: the two failures this text prevents —
  * the members line read as four more result rows, or as one swimmer named
    "Akash Mani, Chinatan S Shetty, ..."
  * legs mis-ordered, or attached to the wrong team, where a record flag or a
    disqualification reason is printed BETWEEN the team row and its members
"""

RELAY_STEPS = """\
STEP 4 — `relay_legs`: the swimmers on each relay team.

This step applies only when the block's discipline carries a multiplier —
"4 x 100m Freestyle", "4 x 200m Freestyle", "4 x 100m Medley". On an individual
event, relay_legs is an empty array. Say nothing else about it.

Under each ranked team an INDENTED line lists its swimmers, comma-separated, in
the order they swam:

     1. Karnataka                    Karnataka              3:26.26
          Akash Mani, Chinatan S Shetty, Aneesh S Gowda, Srihari Nataraj

That line is not a result and is not one swimmer with a very long name. Split it
on the commas and emit ONE entry per name:

  swimmer = the name, trimmed of surrounding spaces, exactly as printed
  leg     = its position on the line, counting from 1 — the FIRST name is leg 1
  team    = the team of the row it sits under
  rank    = that same row's rank

The number of names on the line must equal the multiplier in the discipline: a
"4 x" event gives four legs per team, and there are as many teams here as there
are ranked entries with a members line. If you count three names for a "4 x"
team, a comma has been read as part of a name — look again.

WHICH TEAM A MEMBERS LINE BELONGS TO. It belongs to the nearest ranked entry
ABOVE it, which is not always the line directly above: an annotation can be
printed in between.

     1. Karnataka                    Karnataka              3:26.26
        NMR                                                              <- record flag
          Akash Mani, Chinatan S Shetty, Aneesh S Gowda, Srihari Nataraj <- still Karnataka's

     DSQ Delhi                                              Delhi
         Frist swimmer did 200mt instead of 100mt.                       <- DSQ reason
         Hema, Awesome, Titiksha Rawat, Bhavya Sachdeva                  <- still Delhi's

Skip past a record flag or a disqualification reason — those are handled in
STEP 3c — and attach the members to the ranked entry above them.

A DNS team has no members line at all, and contributes no legs. That is not an
error and nothing should be invented to fill it: a team with no printed members
simply has none.

Every name here must be printed on the members line of the team you attach it
to. Never move a swimmer between teams, never repeat one to reach four, and
never take a name from the individual events elsewhere on the page.
"""
