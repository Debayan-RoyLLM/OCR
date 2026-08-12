"""Deciding which pages are worth paying the expensive vision model for.

Two filters: a blank page is dropped where it stands, and every other page is
read by a cheap vision model that says whether it is worth the expensive one.

Split in two because pages are triaged several at a time — `probe` touches the
PDF and must run under the caller's lock (PyMuPDF is not thread-safe), `decide`
is only the network call. Verdicts are the reason constants from config, not
bare strings: pipeline.py matches on them for the run summary.
"""
from config import (DROP_BLANK, DROP_BY_JUDGE, JUDGE_DPI, KEPT_BY_JUDGE,
                    KEPT_NO_FILTER, PREFILTER)
from llm import llm_judge, page_png_b64
from log import log


def is_blank(page) -> bool:
    """No selectable text and no image: nothing to read, so nothing to ask."""
    return not page.get_text().strip() and not page.get_images(full=True)


def probe(page):
    """Everything that needs the PDF itself: (blank?, the judge's image).

    Blankness is checked before PREFILTER — an empty page has nothing to extract
    even with the filters off — and the render happens here so no fitz call
    escapes the caller's lock."""
    if is_blank(page):
        return True, None
    return False, page_png_b64(page, JUDGE_DPI)


def decide(blank, judge_png):
    """Returns (keep, reason).

    Blank page        -> dropped on the spot, nothing paid.
    Judge says yes    -> extract.
    Judge says no     -> dropped; the expensive call is never made.
    PREFILTER off     -> every non-blank page is extracted.
    """
    if blank:
        return False, DROP_BLANK

    if not PREFILTER:
        return True, KEPT_NO_FILTER

    keep, why = llm_judge(judge_png)
    log.info(f"  judge says {'YES' if keep else 'no'}: {why}")
    return (True, KEPT_BY_JUDGE) if keep else (False, DROP_BY_JUDGE)
