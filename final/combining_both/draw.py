"""The arithmetic of a knockout draw — one rule, stated once.

It is used in two places that must never drift apart:

  * prompts/bracket.py tells the model what the counts have to come to;
  * audit.py checks that the answer it sent back actually does.

Both now read the same three lines below, so a change to the rule cannot leave
the prompt teaching one thing and the auditor enforcing another.
"""


def frame(n: int) -> int:
    """The drawn size of a bracket holding n boxers: the next power of two at or
    above n. 5 boxers are drawn in a frame of 8, 10 or 12 in a frame of 16.

    Integer arithmetic on purpose — the float version, 1 << ceil(log2(n)), is a
    rounding bug waiting to happen on exact powers of two."""
    return 1 << max(0, n - 1).bit_length()


def counts(n: int) -> tuple:
    """(lines, bouts, byes) for a draw of n boxers.

    lines = frame - 1   every line on the chart, bouts and byes alike
    bouts = n - 1       a name on BOTH sides; a knockout of n needs n-1 of them
    byes  = frame - n   a name on one side only
    """
    f = frame(n)
    return f - 1, n - 1, f - n


def example_table(sizes=(16, 12, 10, 5), indent="  ") -> str:
    """The same arithmetic written out as worked examples, for the prompt.

    Generated rather than typed so the numbers the model is shown can never
    disagree with the numbers audit.py will hold it to."""
    rows = []
    for n in sizes:
        lines, bouts, byes = counts(n)
        label = f'"Number of boxers: {n}"'
        rows.append(f"{indent}{label:<23}-> frame {frame(n):>2}: {lines:>2} lines "
                    f"= {bouts:>2} bouts + {byes} byes")
    return "\n".join(rows)
