"""Sanity checks on a page's extracted results and relay legs.

Nothing here looks at the page. Every check asks whether the model's answer
contradicts itself, using only facts that hold for any swimming result from any
federation — never a rule about how one meet-management program lays its pages
out.

The one fact everything leans on: a race is ordered BY TIME. Rank 5 can never be
faster than rank 4, ties are exactly equal times, and the ranks a tie skips are
the ranks it consumed. That arithmetic catches a misread digit in a time, a
dropped row and a flattened tie — the three things an OCR pass actually gets
wrong here — without knowing anything about swimming.
"""
import re
from collections import defaultdict

from log import log


class Warn(str):
    """A complaint carrying how much it matters, so a retry can tell a block
    missing half its swimmers from ranks that merely arrived out of order.

    Still a str: printing, joining and dict.fromkeys dedupe all work.
    """

    def __new__(cls, text, weight=1):
        w = super().__new__(cls, text)
        w.weight = weight
        return w


ARITHMETIC = 5   # the numbers contradict each other: a row or a digit was missed
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


# A swim time as printed: "54.87", "1:54.80", and the hour-long open-water
# "1:02:33.10". Anchored, so "29-01-2025" and "3.5" are not times.
TIME = re.compile(r"^(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,2})\.(\d{1,2})$")

# Printed instead of a rank when the swim did not count.
DNX = {"DNS", "DNF", "DSQ", "WD", "NS", "SCR", "DQ"}

# Printed after the time. Q and R keep their rank; anything else does not.
QUALIFIERS = {"Q", "R"}


def seconds(t):
    """"1:54.80" -> 114.8, for comparing two times. None if it is not a time.

    Also what pipeline.build_table fills time_sec from, so the column in the CSV
    and the number this module checks against can never disagree — which is why
    it is typed against a pandas column too: anything that is not a str, pd.NA
    and None alike, has no time in it."""
    if not isinstance(t, str):
        return None
    m = TIME.match(t.strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    if mi is None:                       # one colon: it was minutes, not hours
        h, mi = None, h
    return (int(h or 0) * 3600 + int(mi or 0) * 60
            + int(s) + float(f"0.{frac}"))


def _block_label(block, many):
    """"[Event 5 Men 4 x 100m Freestyle]" — only when the page holds more than
    one block and a complaint would otherwise be ambiguous."""
    if not many:
        return ""
    bits = [f"Event {block['event_no']}" if block.get("event_no") else None,
            block.get("gender"), block.get("discipline"), block.get("phase")]
    return " [" + " ".join(b for b in bits if b) + "]"


def audit(page_no, blocks, quiet=False):
    """Check a page's result rows against themselves, one event block at a time.

    Per block and never across the page: every block restarts at rank 1, and two
    blocks' times have nothing to do with each other.
    """
    warn = []
    many = len(blocks) > 1

    for block in blocks:
        rows = block.get("results") or []
        where = _block_label(block, many)
        if not rows:
            continue

        # --- the record line, mistaken for a competitor --------------------
        # It has a name and a time and no rank, so it slips into `results`
        # looking like a DNS. Caught by the time: the old record is faster than
        # everything swum today, or it is the identical time to its holder's
        # actual swim.
        holder = (block.get("record_holder") or "").strip().lower()
        rec = seconds(block.get("record_time"))
        for r in rows:
            who = (r.get("name") or r.get("team") or "").strip().lower()
            if holder and who == holder and r.get("rank") is None \
                    and (r.get("status") or "").upper() not in DNX:
                warn.append(Warn(
                    f"'{r.get('name') or r.get('team')}' has no rank and no status "
                    f"but is the record holder{where} — the record line is not a "
                    f"result row", STRUCTURAL))
            if rec is not None and seconds(r.get("time_raw")) == rec \
                    and r.get("rank") is None:
                warn.append(Warn(f"a row with no rank carries the record time "
                                 f"{block['record_time']}{where} — the record "
                                 f"line is not a result row", STRUCTURAL))

        # --- rank, status and time have to agree --------------------------
        for r in rows:
            code = (r.get("status") or "").upper().strip()
            named = r.get("name") or r.get("team") or "?"

            if r.get("rank") is not None and code in DNX:
                warn.append(f"{named} is ranked {r['rank']} and marked {code}"
                            f"{where} — a swim that did not count has no rank")
            if r.get("rank") is None and not code:
                warn.append(f"{named} has neither a rank nor a status{where}")
            if r.get("rank") is not None and not r.get("time_raw"):
                warn.append(Warn(f"{named} is ranked {r['rank']} with no time"
                                 f"{where}", STRUCTURAL))
            if code and code not in DNX and code not in QUALIFIERS:
                warn.append(f"unknown status {code!r} on {named}{where}")

            t = r.get("time_raw")
            if t and seconds(t) is None:
                warn.append(Warn(f"{named}: {t!r} is not a time{where}",
                                 STRUCTURAL))

        ranked = [r for r in rows if r.get("rank") is not None]
        if not ranked:
            continue

        # --- the race was ordered by time ---------------------------------
        ranks = [r["rank"] for r in ranked]
        if ranks != sorted(ranks):
            warn.append(f"ranks not in ascending order{where}")

        timed = [(r["rank"], seconds(r["time_raw"]), r)
                 for r in ranked if seconds(r.get("time_raw")) is not None]
        for (r1, t1, a), (r2, t2, b) in zip(timed, timed[1:]):
            who_a = a.get("name") or a.get("team")
            who_b = b.get("name") or b.get("team")
            if r2 > r1 and t2 < t1:
                warn.append(Warn(
                    f"{who_b} is ranked {r2} behind {who_a} at {r1} but swam "
                    f"faster ({b['time_raw']} < {a['time_raw']}){where} — a "
                    f"digit in one of those times is wrong", ARITHMETIC))
            elif r2 == r1 and t2 != t1:
                warn.append(Warn(
                    f"{who_a} and {who_b} share rank {r1} on different times "
                    f"({a['time_raw']} / {b['time_raw']}){where}", ARITHMETIC))
            elif r2 > r1 and t2 == t1:
                warn.append(Warn(
                    f"{who_a} and {who_b} swam the same time {a['time_raw']} but "
                    f"are ranked {r1} and {r2}{where} — a tie was flattened, and "
                    f"both should be {r1}", ARITHMETIC))

        # --- a tie consumes the ranks it skips ----------------------------
        # 15, 15, 17 is right, and so is 1..N with no repeats. 15, 15, 16 means
        # the page's own numbering was overwritten, and 1, 2, 4 means the row
        # that was rank 3 has been dropped.
        #
        # Counted from the FIRST rank on the page and not from 1, because a
        # block continued from the previous page opens at rank 15 and there is
        # nothing wrong with that.
        seen = {}
        for r in ranked:
            seen[r["rank"]] = seen.get(r["rank"], 0) + 1
        expect = min(seen)
        for rank in sorted(seen):
            if rank > expect:
                warn.append(Warn(
                    f"rank {rank} follows rank {expect - 1}{where} — no tie "
                    f"justifies the gap, so a row between them was dropped",
                    ARITHMETIC))
            elif rank < expect:
                warn.append(Warn(
                    f"rank {rank} follows rank {expect - 1}{where} — the tie "
                    f"above it already used that number", STRUCTURAL))
            expect = max(expect, rank) + seen[rank]

        # --- Q and R are the top of the block, in order -------------------
        marks = [(r["rank"], (r.get("status") or "").upper()) for r in ranked]
        qs = [rk for rk, m in marks if m == "Q"]
        rs = [rk for rk, m in marks if m == "R"]
        if qs and qs != sorted(qs)[:len(qs)] or (qs and min(qs) != min(ranks)):
            warn.append(f"the Q marks are not on the fastest swimmers{where}")
        if qs and rs and min(rs) < max(qs):
            warn.append(f"a reserve (R) is ranked above a qualifier (Q){where}")
        if qs and len(qs) > 10:
            warn.append(f"{len(qs)} swimmers marked Q{where} — a final seats 8 "
                        f"or 10, so Q has been read off the wrong column")

    return _report(page_no, warn, quiet)


def _multiplier(discipline):
    """4 out of "4 x 100m Medley"; None when the event is not a relay."""
    m = re.match(r"\s*(\d+)\s*[x×]\s", discipline or "")
    return int(m.group(1)) if m else None


def audit_relays(page_no, blocks, quiet=False):
    """Check the relay legs against the result rows they hang off."""
    warn = []
    many = len(blocks) > 1

    for block in blocks:
        legs = block.get("relay_legs") or []
        rows = block.get("results") or []
        where = _block_label(block, many)
        n = _multiplier(block.get("discipline"))

        if not n:
            if legs:
                warn.append(f"{len(legs)} relay legs on {block.get('discipline')!r}"
                            f"{where}, which is not a relay")
            continue

        by_team = defaultdict(list)
        for leg in legs:
            by_team[(leg.get("team") or "").strip()].append(leg)

        # A team with no members line is not an error — a DNS has none — but a
        # team with SOME of its swimmers means a name was lost to a comma.
        for team, got in by_team.items():
            if len(got) != n:
                warn.append(Warn(
                    f"{team or '(no team)'} has {len(got)} of {n} legs{where}",
                    ARITHMETIC))
            nums = sorted(l.get("leg") for l in got if l.get("leg") is not None)
            if nums != list(range(1, len(got) + 1)):
                warn.append(Warn(f"{team}'s legs are numbered {nums}{where}, "
                                 f"not 1..{len(got)}", STRUCTURAL))
            names = [(l.get("swimmer") or "").strip().lower() for l in got]
            dupes = {x for x in names if x and names.count(x) > 1}
            if dupes:
                warn.append(Warn(f"{team} swims {sorted(dupes)} twice{where}",
                                 STRUCTURAL))

        # Every members line hangs off a ranked entry; the reverse need not hold.
        teams = {(r.get("team") or "").strip() for r in rows}
        for team in by_team:
            if team and team not in teams:
                warn.append(f"relay legs for {team!r}{where}, which is not one of "
                            f"the ranked teams")

        swam = {(r.get("team") or "").strip() for r in rows
                if r.get("rank") is not None}
        missing = swam - set(by_team)
        if missing and by_team:
            warn.append(f"{len(missing)} ranked team(s) have no swimmers listed"
                        f"{where}: {sorted(missing)}")

    return _report(page_no, warn, quiet)
