"""Builds the row pattern from config.COLUMNS, then reads the PDF line by line."""
import re
import sys

import pdfplumber

from config import COLUMNS, SECTION, SECTION_COL
from fields import FIELD

NAMES = [name for name, _ in COLUMNS]
CASTS = [FIELD[kind][1] for _, kind in COLUMNS]

# Anchored at both ends, so a line must match every column and nothing else —
# that alone rejects headings and column headers, no skip-list needed.
ROW = re.compile("^" + r"\s+".join(FIELD[kind][0] for _, kind in COLUMNS) + "$")

if sum(1 for _, kind in COLUMNS if kind == "text") > 1:
    sys.exit("config.COLUMNS: at most one 'text' column — two free-text "
             "columns side by side cannot be told apart.")


def parse(pdf_file):
    """Returns (rows, unmatched). Unmatched lines are reported, never dropped silently."""
    rows, unmatched, section = [], [], None

    with pdfplumber.open(pdf_file) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").split("\n"):
                line = line.strip()
                if not line:
                    continue

                if SECTION:
                    found = SECTION.match(line)
                    if found:
                        section = found.group(1)
                        continue

                m = ROW.match(line)
                if not m:
                    unmatched.append((page_no, line))
                    continue

                row = {n: cast(m.group(i))
                       for i, (n, cast) in enumerate(zip(NAMES, CASTS), start=1)}
                if SECTION:
                    row[SECTION_COL] = section
                rows.append(row)

    return rows, unmatched
