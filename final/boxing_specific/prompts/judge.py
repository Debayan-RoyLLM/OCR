"""CALL 1 — the page filter.

Asked about every page that is not blank; nothing guesses ahead of it. Biased
toward yes on purpose: a wrongly admitted page costs one extraction call, a
wrongly dropped one loses rows for good.

Must stay in step with STEP 1 in page.py: a page type the judge admits and the
extractor then calls "other" is paid for twice and returns nothing.

The answer key is `worth_reading`, not `has_standings` — ranking tables are
admitted too and have no standings box. llm.llm_judge reads the same name.
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
