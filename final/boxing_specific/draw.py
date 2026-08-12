"""The arithmetic of a knockout draw — one rule, stated once.

prompts/bracket.py teaches the model these counts and audit.py enforces them.
Both read the functions below, so the two cannot drift apart.
"""


def frame(n: int) -> int:
    """The drawn size of a bracket holding n boxers: the next power of two at or
    above n. 5 boxers are drawn in a frame of 8, 10 or 12 in a frame of 16."""
    # Integer arithmetic on purpose: 1 << ceil(log2(n)) misrounds on exact
    # powers of two.
    return 1 << max(0, n - 1).bit_length()


def counts(n: int) -> tuple:
    """(lines, bouts, byes) for a draw of n boxers.

    lines = frame - 1   every line on the chart, bouts and byes alike
    bouts = n - 1       a name on BOTH sides; a knockout of n needs n-1 of them
    byes  = frame - n   a name on one side only
    """
    f = frame(n)
    return f - 1, n - 1, f - n


EXAMPLES = (16, 12, 10, 5)     # a full frame, a few byes, many byes, a small one


def example_table() -> str:
    """EXAMPLES worked out longhand for the prompt, so the numbers the model is
    shown cannot disagree with the numbers audit.py holds it to."""
    rows = []
    for n in EXAMPLES:
        lines, bouts, byes = counts(n)
        label = f'"Number of boxers: {n}"'
        rows.append(f'  {label:<23}-> frame {frame(n):>2}: {lines:>2} lines '
                    f'= {bouts:>2} bouts + {byes} byes')
    return "\n".join(rows)
