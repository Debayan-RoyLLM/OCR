"""Entry point — turn a PDF table into a CSV.

    python3 extract.py [input.pdf] [output.csv]

Edit config.py to point this at a different table.
"""
import os
import sys

import pandas as pd

from config import (DATE_COL, DATE_PATTERN, OUT_CSV, PDF_FILE, SECTION,
                    SECTION_COL)
from parser import NAMES, parse


def report(df, unmatched):
    """Row counts per section, plus every line the pattern rejected."""
    print(f"{len(df)} rows")
    if SECTION:
        for section, n in df.groupby(SECTION_COL, sort=False).size().items():
            print(f"  {n:>3}  {section}")
        blank = df[SECTION_COL].isna().sum()
        if blank:
            print(f"! {blank} rows had no heading above them")

    print(f"\n{len(unmatched)} lines did not match the pattern:")
    for page_no, line in unmatched[:8]:
        print(f"    p{page_no}: {line}")
    if len(unmatched) > 8:
        print(f"    ... and {len(unmatched) - 8} more")


def main(argv):
    pdf_file = argv[1] if len(argv) > 1 else PDF_FILE
    out_csv  = argv[2] if len(argv) > 2 else OUT_CSV

    if not os.path.exists(pdf_file):
        sys.exit(f"no such file: {pdf_file}\n"
                 f"usage: python3 {os.path.basename(argv[0])} [input.pdf] [output.csv]")

    rows, unmatched = parse(pdf_file)
    if not rows:
        sys.exit("nothing matched — check config.COLUMNS against the printed table")

    found = DATE_PATTERN.search(os.path.basename(pdf_file))
    df = pd.DataFrame(rows)
    df.insert(0, DATE_COL, found.group(1) if found else "")

    order = [DATE_COL] + ([SECTION_COL] if SECTION else []) + NAMES
    df[order].to_csv(out_csv, index=False)

    report(df, unmatched)
    print(f"\n-> {out_csv}")


if __name__ == "__main__":
    main(sys.argv)
