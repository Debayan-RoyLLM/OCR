"""The extraction contract: response schema and the instructions that go with it."""

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "draw_sheet",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "is_draw_sheet": {"type": "boolean"},
                "event": {"type": ["string", "null"],
                          "description": "Tournament name, the largest heading at the top."},
                "division": {"type": ["string", "null"],
                             "description": "Weight/category line, e.g. 'Elite Women - 48 Kg (EW-48 kg)'."},
                "date_raw": {"type": ["string", "null"],
                             "description": "The 'As of' date exactly as printed."},
                "date_iso": {"type": ["string", "null"],
                             "description": "Same date as YYYY-MM-DD."},
                "standings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
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
                        },
                        "required": ["rank", "name_short", "country", "medal", "name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["is_draw_sheet", "event", "division", "date_raw", "date_iso", "standings"],
            "additionalProperties": False,
        },
    },
}

PROMPT = """\
STEP 1 — Is this page a tournament Draw Sheet / bracket? Set is_draw_sheet.
If false: nulls everywhere and an empty standings array. Stop.

STEP 2 — Read the header: the tournament name (largest text at top), the weight
division line, and the "As of" date. Copy each EXACTLY as printed.

STEP 3 — Find the box labelled "Standings:". Extract ONLY the lines inside it.
Ignore the bracket tree, all bout scores (WP 5:0, RSC R1), every "Bye", the NOTES
and LEGEND sections, and the page footer.

Each standings line has this exact form:

    <rank> . <NAME> (<CCC>) <medal?>

Parse it field by field:
  rank       = the digit before the period. TRANSCRIBE IT AS PRINTED.
  name_short = the text between the period and the opening parenthesis.
  country    = the 3 letters inside the parentheses.
  medal      = Gold / Silver / Bronze, or null if nothing follows.

CRITICAL — ranks tie and repeat. Two bronze medallists are BOTH printed "3." and
must BOTH be rank 3. Four fifth-place boxers are ALL "5." and must ALL be rank 5.
Do NOT convert repeated ranks into a 1,2,3,4,5 sequence. If you output an
unbroken 1,2,3,4,5 you have made an error — re-read the printed digits.

CRITICAL — the 3-letter country code goes in `country` and NOWHERE ELSE. It must
never appear in name_short or name.

STEP 4 — For each boxer, look up their full name in the bracket's Team/Name column
on the left and put it in `name`. The box abbreviates surnames: "RANI M" is
"RANI MANJU"; a single letter like "N" or "K" is the full single-word surname such
as "NITU" or "KUSUM". If you cannot match one confidently, return null — do not guess.

Never invent a boxer who is not printed in the Standings box.
"""

TRIAGE_PROMPT = (
    "Does this page contain a bracket tree, flow chart, graph, or other "
    "line-and-box diagram? Plain prose, a title page, a plain table, or a "
    "list of results is NOT a diagram. Reply with JSON only: "
    '{"has_figure": true} or {"has_figure": false}'
)
