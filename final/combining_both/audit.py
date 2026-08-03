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
