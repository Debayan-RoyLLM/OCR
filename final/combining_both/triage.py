"""Deciding which pages are worth paying the expensive vision model for.

Two filters and nothing else:

  1. a blank page is dropped where it stands — no model is asked about a page
     with nothing on it;
  2. every other page is read by a cheap vision model, which says whether it is
     worth the expensive one.

There is no keyword or geometry guess in front of the judge. Guessing a page's
contents from its shape was cheap but wrong often enough that the judge ended up
overruling it on nearly every page anyway.

The work is split in two because pages are triaged several at a time: `probe`
touches the PDF and must run under the caller's lock (PyMuPDF documents are not
thread-safe), `decide` is only the network call and the verdict. Each verdict is
one of the four reasons named in config, never a bare string — pipeline.py
matches on them when it prints the run summary.
"""
from config import (DROP_BLANK, DROP_BY_JUDGE, JUDGE_DPI, KEPT_BY_JUDGE,
                    KEPT_NO_FILTER, LLM_FILTER, PREFILTER)
from llm import llm_judge, page_png_b64
from log import log


def is_blank(page) -> bool:
    """No selectable text and no image. There is nothing on the page to read, so
    no model — cheap or expensive — is worth asking about it."""
    return not page.get_text().strip() and not page.get_images(full=True)


def probe(page):
    """Everything that needs the PDF itself: (blank?, the judge's image).

    Checked before PREFILTER — an empty page has nothing to extract even when
    the filters are switched off for a debugging run — and rendered here so no
    fitz call happens off the caller's lock."""
    if is_blank(page):
        return True, None
    return False, page_png_b64(page, JUDGE_DPI)


def decide(blank, judge_png):
    """Returns (keep, reason).

    Blank page        -> dropped on the spot, nothing paid.
    Judge says yes    -> extract.
    Judge says no     -> dropped; the expensive call is never made.
    LLM_FILTER off    -> every non-blank page is extracted.
    """
    if blank:
        return False, DROP_BLANK

    if not PREFILTER or not LLM_FILTER:
        return True, KEPT_NO_FILTER

    keep, why = llm_judge(judge_png)
    log.info(f"  judge says {'YES' if keep else 'no'}: {why}")
    return (True, KEPT_BY_JUDGE) if keep else (False, DROP_BY_JUDGE)
