"""Deciding which pages are worth paying the expensive vision model for."""
from config import (HINTS, LLM_TRIAGE, MIN_BOXES, MIN_STROKES, PREFILTER,
                    VECTOR_TRIAGE)
from llm import llm_has_figure


def looks_like_figure(page) -> bool:
    """Stage 2 — free, local. Bracket trees and flow charts are made of many
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


def decide(page):
    """Returns (keep, reason). Ladder runs cheapest-first and short-circuits."""
    if not PREFILTER:
        return True, "prefilter off"

    t = page.get_text().lower()
    if not t.strip():
        return True, "no text layer"
    if any(x in t for x in HINTS):
        return True, "keyword"
    if VECTOR_TRIAGE and looks_like_figure(page):
        return True, "figure geometry"
    if LLM_TRIAGE and llm_has_figure(page):
        return True, "llm triage"
    return False, "no keyword, no figure"
