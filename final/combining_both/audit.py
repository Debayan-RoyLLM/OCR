"""Sanity checks on a page's extracted standings."""


def audit(page_no, d, rows):
    """Cheap checks that catch the exact failures seen in the earlier run."""
    warn = []
    ranks = [r["rank"] for r in rows if r["rank"] is not None]
    bracket = d.get("page_type") == "draw_sheet"

    # Bracket-only: a ranking table is SUPPOSED to run 1,2,3,4,5 and has no medals.
    if bracket:
        if len(ranks) >= 4 and ranks == list(range(1, len(ranks) + 1)):
            warn.append("ranks are a perfect 1..N sequence — ties likely flattened")

        bronze = sum(1 for r in rows if (r["medal"] or "").lower() == "bronze")
        at3 = sum(1 for r in rows if r["rank"] == 3)
        if bronze and bronze != at3:
            warn.append(f"{bronze} bronze medals but {at3} rows at rank 3")

    if ranks != sorted(ranks):
        warn.append("ranks not in ascending order")

    for r in rows:
        for f in ("name_short", "name"):
            v = (r[f] or "").strip()
            if len(v) == 3 and v.isupper() and v.isalpha() and v == (r["country"] or ""):
                warn.append(f"country code leaked into {f}: {v}")

    # Division is per row now: a stacked page has none at the top and one per row.
    if not d["division"] and not all(r.get("division") for r in rows):
        warn.append("division missing")

    for w in warn:
        print(f"  ! p{page_no}: {w}")
    return warn


def audit_bouts(page_no, bouts, boxers_drawn=None):
    """The bracket's own consistency. A bout the model half-read usually shows up
    as a winner who was not in it, or a corner colour where a name belongs."""
    warn = []
    colours = {"red", "blue"}

    for b in bouts:
        a, bb, w = b.get("boxer_a"), b.get("boxer_b"), b.get("winner")
        if w and w.strip().lower() in colours:
            warn.append(f"winner is a corner colour, not a name: {w}")
        elif w and w not in (a, bb):
            warn.append(f"winner '{w}' boxed in no bout on this page")
        if not bb and (b.get("result") or "").strip().lower() != "bye":
            warn.append(f"one-sided bout with no Bye: {a} / {b.get('result')}")

    rounds = {b["round"] for b in bouts if b.get("round")}
    if len(bouts) > 1 and not rounds:
        warn.append(f"{len(bouts)} bouts but no round named on any of them")

    # The sheet says how many boxers it drew, and a knockout of N is decided in
    # exactly N-1 real bouts. Off by one and a pair was read across two boxes.
    if boxers_drawn:
        real = sum(1 for b in bouts if b.get("boxer_a") and b.get("boxer_b"))
        if real != boxers_drawn - 1:
            warn.append(f"{boxers_drawn} boxers drawn needs {boxers_drawn - 1} "
                        f"two-sided bouts, got {real}")

    for w in dict.fromkeys(warn):
        print(f"  ! p{page_no}: {w}")
    return warn
