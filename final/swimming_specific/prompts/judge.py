"""CALL 1 — the page filter.

Asked about every page that is not blank; nothing guesses ahead of it. Biased
toward yes on purpose: a wrongly admitted page costs one extraction call, a
wrongly dropped one loses rows for good.

Must stay in step with STEP 1 in page.py: a page type the judge admits and the
extractor then calls "other" is paid for twice and returns nothing. In particular
both must draw the line at TIMES ACHIEVED, so a start list is refused twice.

Off by default in this configuration (config.PREFILTER) — a meet-manager result
PDF is result pages front to back and the judge would pass every one of them.
Kept for the mixed programme booklet that has schedules bound in with results.
"""

JUDGE_PROMPT = (
    "Decide whether this page is worth reading in full.\n"
    "Answer true if the page shows SWIMMING RESULTS — numbered finishing places "
    "with times, for swimmers or for relay teams — even if faint, rotated, "
    "scanned, or only partly visible.\n"
    "Answer false if it shows no times achieved: a start list or heat sheet of "
    "lane draws, a psych sheet, a session schedule, a medal tally or points "
    "table, a cover page, a rulebook page, or plain prose.\n"
    "If you are genuinely unsure, answer true.\n"
    'Reply with JSON only: {"worth_reading": true, "why": "<six words max>"}'
)
