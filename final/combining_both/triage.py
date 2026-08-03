"""Deciding which pages are worth paying the expensive vision model for.

Two filters and nothing else:

  1. a blank page is dropped where it stands — no model is asked about a page
     with nothing on it;
  2. every other page is read by a cheap vision model, which says whether it is
     worth the expensive one.

There is no keyword or geometry guess in front of the judge. Guessing a page's
contents from its shape was cheap but wrong often enough that the judge ended up
overruling it on nearly every page anyway.
"""
from config import JUDGE_DPI, LLM_FILTER, PREFILTER
from llm import llm_judge


def is_blank(page) -> bool:
    """No selectable text and no image. There is nothing on the page to read, so
    no model — cheap or expensive — is worth asking about it."""
    return not page.get_text().strip() and not page.get_images(full=True)


def decide(page):
    """Returns (keep, reason).

    Blank page        -> dropped on the spot, nothing paid.
    Judge says yes    -> extract.
    Judge says no     -> dropped; the expensive call is never made.
    LLM_FILTER off    -> every non-blank page is extracted.
    """
    # Checked before PREFILTER: an empty page has nothing to extract even when
    # the filters are switched off for a debugging run.
    if is_blank(page):
        return False, "blank page"

    if not PREFILTER or not LLM_FILTER:
        return True, "no filter"

    keep, why = llm_judge(page)
    print(f"  judge says {'YES' if keep else 'no'}: {why}")
    return (True, "judge") if keep else (False, "judge rejected")
