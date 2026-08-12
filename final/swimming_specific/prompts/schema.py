"""CALL 2, the contract — what the extractor is allowed to return.

Strict JSON schema, so the API itself rejects a missing field, a wrong type or an
out-of-enum value. What it CANNOT check is whether the values are true; that is
what audit.py is for.

A results page is a stack of EVENT BLOCKS, so the answer is one array of blocks
rather than one flat table. The block holds what its rows share — event number,
discipline, phase — and the rows hold the swimmers. pipeline.unpack flattens it.

Two row shapes come out of one block:
    results    — one entry per swimmer, or per TEAM on a relay  (see results.py)
    relay_legs — one entry per relay swimmer, in swum order     (see relay.py)
"""

# The record line above each block: the mark to beat, not a competitor. Kept so
# the page says why it is there, and so audit.py can catch it being mistaken for
# a result row.
_RECORD = {
    "record_type": {"type": ["string", "null"],
                    "description": "The record's label as printed at the start of the line: 'NATIONAL GAMES', 'MEET RECORD', 'NR'. Null if the block prints no record line."},
    "record_time": {"type": ["string", "null"],
                    "description": "The record time exactly as printed, e.g. '1:49.09'."},
    "record_holder": {"type": ["string", "null"],
                      "description": "Who holds it — a swimmer's name, or a team's name on a relay."},
    "record_nation": {"type": ["string", "null"],
                      "description": "The 3-letter nation code on the record line, e.g. 'IND'."},
    "record_place": {"type": ["string", "null"],
                     "description": "Where it was set, as printed, e.g. 'GOA'."},
    "record_date": {"type": ["string", "null"],
                    "description": "The date on the record line as YYYY-MM-DD. This is a PAST date and is never the session date."},
}

_RESULT_ROW = {
    "rank": {"type": ["integer", "null"],
             "description": "The digit printed before the period. Transcribe it; never renumber. Null when the rank column holds a status code (DNS, DSQ) instead of a number."},
    "name": {"type": ["string", "null"],
             "description": "The swimmer's name as printed. On a RELAY this is null — the team goes in `team`."},
    "team": {"type": ["string", "null"],
             "description": "The club / state / unit the entry swims for — the value in the second name column, whatever that column is LABELLED."},
    "time_raw": {"type": ["string", "null"],
                 "description": "The finishing time exactly as printed: '1:54.80', '54.87'. Null when no time is printed, as on a DNS."},
    "status": {"type": ["string", "null"],
               "description": "The qualifying mark printed after the time (Q, R) or the code printed instead of a rank (DNS, DNF, DSQ, WD, NS). Null if neither is printed."},
    "remark": {"type": ["string", "null"],
               "description": "Free text printed on its own line under this entry, such as a disqualification reason: 'Early Start'. Null if there is none."},
    "record_set": {"type": ["boolean", "null"],
                   "description": "True when a record flag (NMR, NGR, NR, MR) is printed under this entry, meaning THIS swim set a record. Null or false otherwise."},
}

_RELAY_LEG = {
    "rank": {"type": ["integer", "null"],
             "description": "The rank of the team this swimmer swam for, copied from its result row."},
    "team": {"type": ["string", "null"],
             "description": "The team this swimmer swam for."},
    "leg": {"type": ["integer", "null"],
            "description": "Position in the swum order, counting from 1 — the first name on the line is leg 1."},
    "swimmer": {"type": ["string", "null"],
                "description": "The swimmer's name, exactly as printed on the members line."},
}


def _obj(props, description=None):
    """An object every one of whose properties is required — what strict mode
    demands, spelled once instead of beside each block."""
    out = {"type": "object", "properties": props,
           "required": list(props), "additionalProperties": False}
    if description:
        out["description"] = description
    return out


SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "swim_results",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string",
                              "enum": ["result_list", "other"],
                              "description": "'result_list' if the page shows finishing places with times. 'other' means nothing to extract."},
                "event": {"type": ["string", "null"],
                          "description": "The MEET name, the largest heading at the top of the page, e.g. '38th NATIONAL GAMES 2025'. Not the name of a single race."},
                "date_raw": {"type": ["string", "null"],
                             "description": "The session date exactly as printed at the top of the first event block on this page. Not tidied."},
                "date_iso": {"type": ["string", "null"],
                             "description": "That same session date as YYYY-MM-DD. Never the date off a record line."},
                "date_source": {"type": ["string", "null"],
                                "description": "Where the date was found, a few words: 'event block header', 'footer', 'meet subtitle'."},
                "blocks": {
                    "type": "array",
                    "description": "One entry per EVENT BLOCK on the page, top to bottom. A page carrying the tail of a block begun on the previous page still gets a block here.",
                    "items": _obj({
                        "event_no": {"type": ["integer", "null"],
                                     "description": "The number in the 'Event N' heading. Null if the block prints none."},
                        "discipline": {"type": ["string", "null"],
                                       "description": "The race itself, without the gender: '200m Freestyle', '4 x 100m Medley'. Keep the relay multiplier."},
                        "gender": {"type": ["string", "null"],
                                   "description": "'Men', 'Women', 'Mixed', or 'Boys'/'Girls' — exactly the word printed before the discipline."},
                        "age_group": {"type": ["string", "null"],
                                      "description": "The category printed at the right-hand end of the event title line: 'Open', 'Group I', '15-17 Yrs'."},
                        "phase": {"type": ["string", "null"],
                                  "description": "The word after 'Results' on the second line: 'Prelim', 'Final', 'Semifinal'. Null when it prints 'Results' alone."},
                        "date_raw": {"type": ["string", "null"],
                                     "description": "The session date printed at the left of this block's second line, as printed. Null on a continuation block, which prints none."},
                        "date_iso": {"type": ["string", "null"],
                                     "description": "That same date as YYYY-MM-DD. Null on a continuation block."},
                        "continued": {"type": "boolean",
                                      "description": "True when this block is the TAIL of one begun on an earlier page — its heading is the single comma-separated line 'Event 2, Women, 200m Freestyle, Prelim, Open' with no record line beneath it."},
                        **_RECORD,
                        "results": {
                            "type": "array",
                            "description": "Every entry listed under this block's Rank/Time column labels, including entries that did not finish. Never the record line above them.",
                            "items": _obj(_RESULT_ROW),
                        },
                        "relay_legs": {
                            "type": "array",
                            "description": "On a relay block, one entry per named swimmer on every team's members line. Empty array on an individual event.",
                            "items": _obj(_RELAY_LEG),
                        },
                    }),
                },
            },
            "required": ["page_type", "event", "date_raw", "date_iso",
                         "date_source", "blocks"],
            "additionalProperties": False,
        },
    },
}
