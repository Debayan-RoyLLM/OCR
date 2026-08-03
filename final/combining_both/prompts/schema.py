"""CALL 2, the contract — what the extractor is allowed to return.

Strict JSON schema, so the API itself rejects a missing field, a wrong type or an
out-of-enum value. What it CANNOT check is whether the values are true; that is
what audit.py is for.

Two arrays come back from one page:
    standings — one entry per boxer, where they FINISHED   (see standings.py)
    bouts     — one entry per fight, who boxed WHOM        (see bracket.py)
"""

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "draw_sheet",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string",
                              "enum": ["draw_sheet", "ranking_table", "other"],
                              "description": "What kind of page this is. 'other' means nothing to extract."},
                "event": {"type": ["string", "null"],
                          "description": "Tournament name, the largest heading at the top."},
                "division": {"type": ["string", "null"],
                             "description": "The page's weight/category line, e.g. 'Elite Women - 48 Kg (EW-48 kg)'. Null if the page stacks several categories — then each row carries its own."},
                "date_raw": {"type": ["string", "null"],
                             "description": "The date exactly as printed anywhere on the page — header, title, or footer. Not tidied."},
                "date_iso": {"type": ["string", "null"],
                             "description": "The same date as YYYY-MM-DD. Month-and-year only becomes the 1st of that month. Null if no date is printed."},
                "date_source": {"type": ["string", "null"],
                                "description": "Where the date was found, a few words: 'As of line', 'title', 'footer Report Created', etc."},
                "boxers_drawn": {"type": ["integer", "null"],
                                 "description": "The figure printed as 'Number of boxers: N' on a draw sheet. Null if the page prints no such line."},
                "rounds_printed": {
                    "type": "array",
                    "description": "The round headings printed across the top of the bracket, LEFT TO RIGHT and exactly as written — e.g. ['Preliminaries','Quarterfinals','Semifinals','Final'] or ['Round of 16','1/4 Finals','1/2 Finals','Final']. Empty array when the page draws no bracket.",
                    "items": {"type": "string"},
                },
                "standings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "division": {"type": ["string", "null"],
                                         "description": "The weight class / event type THIS row sits under, copied from the nearest heading above it or from the row's own weight-category column. Null only if the page shows no category at all."},
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
                            "previous_rank": {"type": ["string", "null"],
                                              "description": "Ranking tables only: the previous-rank column as printed, e.g. '14' or 'x'. Null on draw sheets."},
                            "points_total": {"type": ["number", "null"],
                                             "description": "Ranking tables only: the total/final points column. Null on draw sheets."},
                        },
                        "required": ["division", "rank", "name_short", "country",
                                     "medal", "name", "previous_rank", "points_total"],
                        "additionalProperties": False,
                    },
                },
                "bouts": {
                    "type": "array",
                    "description": "Every individual bout the page shows — read off the bracket on a draw sheet, or off the rows of a bout-results table. Empty array when the page shows neither.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "division": {"type": ["string", "null"],
                                         "description": "The weight class this bout was fought in."},
                            "round": {"type": ["string", "null"],
                                      "description": "The stage this bout belongs to, exactly as printed above its column: 'Preliminaries', 'Quarterfinals', 'Semifinals', 'Final'. Null if the page prints no round."},
                            "bout_no": {"type": ["integer", "null"],
                                        "description": "The bout number, if the page prints one. Null on a bracket that shows none."},
                            "boxer_a": {"type": ["string", "null"],
                                        "description": "The boxer entering from the TOP of the pair, or the RED corner on a bout-results table."},
                            "country_a": {"type": ["string", "null"],
                                          "description": "3-letter code for boxer_a."},
                            "boxer_b": {"type": ["string", "null"],
                                        "description": "The boxer entering from the BOTTOM of the pair, or the BLUE corner. Null when boxer_a had a Bye."},
                            "country_b": {"type": ["string", "null"],
                                          "description": "3-letter code for boxer_b."},
                            "winner": {"type": ["string", "null"],
                                       "description": "The NAME of the boxer who advanced — never a corner colour. Null if the bout has no result yet."},
                            "result": {"type": ["string", "null"],
                                       "description": "The verdict exactly as printed: 'WP 5:0', 'RSC R1', 'Bye', 'WO', 'ABD', 'DSQ'."},
                        },
                        "required": ["division", "round", "bout_no", "boxer_a",
                                     "country_a", "boxer_b", "country_b",
                                     "winner", "result"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["page_type", "event", "division", "date_raw", "date_iso",
                         "date_source", "boxers_drawn", "rounds_printed",
                         "standings", "bouts"],
            "additionalProperties": False,
        },
    },
}
