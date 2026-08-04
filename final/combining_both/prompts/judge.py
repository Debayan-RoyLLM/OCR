"""CALL 1 — the page filter.

Asked about every page that is not blank; nothing guesses ahead of it. Biased
toward yes on purpose: a wrongly admitted page costs one extraction call, a
wrongly dropped one loses rows for good.

Must stay in step with STEP 1 in `page.py`. If the judge admits a page type the
extractor then calls "other", you pay twice and get nothing back.

The answer key is `worth_reading`, not `has_standings`: the judge admits ranking
tables too, and a ranking table has no standings box. llm.llm_judge reads the
same name — change one and you must change the other.
"""

JUDGE_PROMPT = (
    "Decide whether this page is worth reading in full.\n"
    "Answer true if the page shows EITHER a tournament draw sheet / bracket with "
    "a standings box, OR a ranking table of numbered athletes with country codes "
    "— even if faint, rotated, scanned, or only partly visible.\n"
    "Answer false if it is a cover page, a session schedule, a bout order list, "
    "a rulebook page, a legend, a photo, or plain prose.\n"
    "If you are genuinely unsure, answer true.\n"
    'Reply with JSON only: {"worth_reading": true, "why": "<six words max>"}'
)
