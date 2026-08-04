"""Sanity checks on a page's extracted standings and bouts.

Nothing here looks at the page. Every check asks whether the model's answer
contradicts itself, using only arithmetic that holds for any knockout draw from
any federation — never a rule about how one publisher lays its sheets out. That
arithmetic is draw.py, which is also what prompts/bracket.py teaches from.
"""
import re
from collections import defaultdict

from draw import frame as draw_frame
from log import log


def _tokens(name):
    """A name as a set of comparable words: case, punctuation and word order all
    vary between the bracket and the result line on the same sheet."""
    return set(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def named(who, *boxers):
    """Is `who` one of `boxers`? Subset, not equality, so "SMITH" matches
    "SMITH John". A name that is genuinely absent shares no word with either
    corner and is still caught."""
    w = _tokens(who)
    return bool(w) and any(w <= _tokens(b) or _tokens(b) <= w
                           for b in boxers if b)


class Warn(str):
    """A complaint carrying how much it matters, so a retry can tell a bracket
    three bouts short from ranks that merely arrived out of order.

    Still a str: printing, joining and dict.fromkeys dedupe all work.
    """

    def __new__(cls, text, weight=1):
        w = super().__new__(cls, text)
        w.weight = weight
        return w


ARITHMETIC = 5   # the counts do not add up: a column or a pair was missed
STRUCTURAL = 3   # the shape of the answer is wrong, e.g. ties flattened


def severity(warns) -> int:
    """What a set of complaints is worth, for comparing two reads of one page."""
    return sum(getattr(w, "weight", 1) for w in warns)


def _report(page_no, warn, quiet):
    """Drop the repeats, say them once, hand them back. `quiet` scores a retry
    without printing an answer that may yet be discarded."""
    warn = list(dict.fromkeys(warn))
    if not quiet:
        for w in warn:
            log.warning(f"  ! p{page_no}: {w}")
    return warn


def audit(page_no, d, rows, quiet=False):
    """Check a page's standings against themselves."""
    warn = []
    bracket = d.get("page_type") == "draw_sheet"

    # One page can stack a dozen weight classes, each restarting at rank 1, so
    # every check runs per division: a "3" then a "1" is the next class starting.
    blocks = defaultdict(list)
    for r in rows:
        blocks[r.get("division")].append(r)

    for div, block in blocks.items():
        where = f" [{div}]" if len(blocks) > 1 else ""
        ranks = [r.get("rank") for r in block if r.get("rank") is not None]

        # Bracket-only: a ranking table is SUPPOSED to run 1,2,3,4,5, no medals.
        if bracket:
            if len(ranks) >= 4 and ranks == list(range(1, len(ranks) + 1)):
                warn.append(Warn(f"ranks are a perfect 1..N sequence{where} — "
                                 f"ties likely flattened", STRUCTURAL))

            bronze = sum(1 for r in block if (r.get("medal") or "").lower() == "bronze")
            at3 = sum(1 for r in block if r.get("rank") == 3)
            if bronze and bronze != at3:
                warn.append(f"{bronze} bronze medals but {at3} rows at rank 3{where}")

        if ranks != sorted(ranks):
            warn.append(f"ranks not in ascending order{where}")

    # No previous-rank column tempts the model into copying the one next to it.
    prev = [(r.get("previous_rank"), r.get("rank")) for r in rows if r.get("previous_rank")]
    if len(prev) >= 4 and all(str(p) == str(k) for p, k in prev):
        warn.append(f"previous_rank copies rank on all {len(prev)} rows — likely no such column")

    for r in rows:
        for f in ("name_short", "name"):
            v = (r.get(f) or "").strip()
            if len(v) == 3 and v.isupper() and v.isalpha() and v == (r.get("country") or ""):
                warn.append(f"country code leaked into {f}: {v}")

    if not d.get("division") and not all(r.get("division") for r in rows):
        warn.append("division missing")

    return _report(page_no, warn, quiet)


def audit_bouts(page_no, bouts, boxers_drawn=None, rounds_printed=None, quiet=False):
    """Check a page's bouts against themselves and against boxers_drawn."""
    warn = []
    colours = {"red", "blue"}
    two_sided = [b for b in bouts if b.get("boxer_a") and b.get("boxer_b")]
    byes = [b for b in bouts if not (b.get("boxer_a") and b.get("boxer_b"))]

    for b in bouts:
        a, bb, w = b.get("boxer_a"), b.get("boxer_b"), b.get("winner")
        if w and w.strip().lower() in colours:
            warn.append(f"winner is a corner colour, not a name: {w}")
        elif w and not named(w, a, bb):
            warn.append(f"winner '{w}' boxed in no bout on this page")
        if not bb and (b.get("result") or "").strip().lower() != "bye":
            warn.append(f"one-sided bout with no Bye: {a} / {b.get('result')}")

    used = [b.get("round") for b in bouts if b.get("round")]
    # Bout-results tables number their bouts and print no round, so a missing
    # round is only suspicious on a page that numbers nothing either.
    numbered = any(b.get("bout_no") for b in bouts)
    if len(bouts) > 1 and not used and not numbered:
        warn.append(f"{len(bouts)} bouts but no round named on any of them")

    if rounds_printed:
        stray = {r for r in used if r not in rounds_printed}
        if stray:
            warn.append(f"round(s) {sorted(stray)} not among the headings "
                        f"printed on the page {rounds_printed}")

    # All of this follows from the one number the sheet prints. See draw.py:
    # N boxers -> N-1 bouts, drawn in a frame of frame-1 lines, frame-N of byes.
    if boxers_drawn and boxers_drawn > 1:
        frame = draw_frame(boxers_drawn)
        short = len(two_sided) != boxers_drawn - 1
        if short:
            warn.append(Warn(f"{boxers_drawn} boxers drawn needs {boxers_drawn - 1} "
                             f"two-sided bouts, got {len(two_sided)}", ARITHMETIC))

        # Only when the bouts are already wrong or the byes are half there: a
        # federation that draws no bye lines at all is not an error.
        if (short or byes) and len(bouts) != frame - 1:
            warn.append(Warn(f"a frame of {frame} holds {frame - 1} lines "
                             f"({boxers_drawn - 1} bouts + {frame - boxers_drawn} byes), "
                             f"got {len(bouts)} ({len(two_sided)} + {len(byes)})",
                             ARITHMETIC))

        # Pairs halve left to right: frame/2, frame/4 ... 1 in printed order.
        if rounds_printed and short:
            counts = [sum(1 for b in bouts if b.get("round") == r) for r in rounds_printed]
            want = [frame >> (i + 1) for i in range(len(rounds_printed))]
            if counts != want:
                warn.append(Warn("lines per round should halve "
                                 f"{dict(zip(rounds_printed, want))}, got "
                                 f"{dict(zip(rounds_printed, counts))}", ARITHMETIC))

    return _report(page_no, warn, quiet)
