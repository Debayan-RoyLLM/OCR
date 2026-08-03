"""Deciding which pages are worth paying the expensive vision model for.

Every enabled gate must pass. A page that fails one is not thrown away — a cheap
vision model reads it and has the final say.
"""
from config import (HINTS, JUDGE_FALLBACK, LLM_TRIAGE, MIN_BOXES, MIN_STROKES,
                    PREFILTER, VECTOR_TRIAGE)
from llm import llm_has_figure, llm_judge


def looks_like_figure(page) -> bool:
    """Gate 3 — free, local. Bracket trees and flow charts are made of many
    short axis-aligned strokes and/or boxes; body text and tables are not."""
    h = v = boxes = 0
    try:
        drawings = page.get_drawings()
    except Exception:
        return False

    for d in drawings:
        for it in d["items"]:
            kind = it[0]
            if kind == "l":                                  # line segment
                p, q = it[1], it[2]
                dx, dy = abs(p.x - q.x), abs(p.y - q.y)
                if dy <= 1.5 and dx >= 25:
                    h += 1
                elif dx <= 1.5 and dy >= 12:
                    v += 1
            elif kind == "re":                               # rectangle
                r = it[1]
                if r.width >= 25 and r.height <= 2:
                    h += 1                                   # rule drawn as thin rect
                elif r.height >= 12 and r.width <= 2:
                    v += 1
                elif r.width >= 30 and r.height >= 15:
                    boxes += 1

    if h >= 5 and v >= 3 and h + v >= MIN_STROKES:
        return True                                          # line-and-box tree
    if boxes >= MIN_BOXES:
        return True                                          # boxed flow chart
    # scanned or image-only figure page: a picture and almost no selectable text
    return bool(page.get_images(full=True)) and len(page.get_text().strip()) < 400


def run_gates(page) -> dict:
    """Every gate answers the same question: does this page look like it holds
    standings? Returns {gate name: passed}. Free gates run first — the paid gate
    is only asked once the free ones have all agreed."""
    text = page.get_text()
    gates = {
        "content":  bool(text.strip()) or bool(page.get_images(full=True)),
        "keyword":  any(h in text.lower() for h in HINTS),
    }
    if VECTOR_TRIAGE:
        gates["geometry"] = looks_like_figure(page)
    if LLM_TRIAGE and all(gates.values()):
        gates["mini model"] = llm_has_figure(page)
    return gates


def decide(page):
    """Returns (keep, reason).

    All gates pass          -> extract.
    Any gate fails          -> the judge reads the page and decides.
    Judge disabled          -> drop for free.
    """
    if not PREFILTER:
        return True, "prefilter off"

    gates = run_gates(page)
    failed = [name for name, ok in gates.items() if not ok]
    if not failed:
        return True, "all gates"

    if not JUDGE_FALLBACK:
        return False, "gates failed"

    keep, why = llm_judge(page)
    print(f"  gates failed [{', '.join(failed)}] -> judge says "
          f"{'YES' if keep else 'no'}: {why}")
    return keep, "judge" if keep else "judge rejected"
