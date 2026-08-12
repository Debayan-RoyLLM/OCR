"""The only file you edit when pointing this at a different table."""
import re

# =============================================================================
#  CHANGE VARIABLE NAMES HERE
#
#  One entry per printed column, left to right.
#    "Rank"  -> the CSV header. Rename this to whatever you want the output
#               column called. Changing it never affects the parsing.
#    "int"   -> the SHAPE of the value as printed. This DOES affect parsing;
#               it must describe what is actually on the page.
#               Shapes available: see fields.py
#
#  Add / remove / reorder lines to match the new table. The row pattern is
#  built from this list, so the two can never fall out of step.
# =============================================================================
COLUMNS = [
    ("Rank",          "int"),          # 1, 2, 15
    ("Previous Rank", "code_or_int"),  # 14, or the literal "x" for a new entry
    ("Athlete",       "text"),         # any number of words — only ONE of these
    ("NF",            "upper3"),       # IND, KAZ, UZB
    ("2024 Points",   "num"),          # 0, 56.25
    ("2025 Points",   "num"),
    ("Total Points",  "num"),
]

# Heading that applies to every row under it, until the next heading appears.
# Set SECTION = None if the table has no such heading.
SECTION     = re.compile(r"^((?:MEN|WOMEN)'S\s+\S+\s+RANKINGS)$", re.I)
SECTION_COL = "Category"                       # rename freely

# Constant stamped on every row, read from the filename.
DATE_PATTERN = re.compile(r"(\d{4}-[A-Za-z]+)")   # matches 2026-July
DATE_COL     = "Date"                             # rename freely

# Defaults when no paths are given on the command line.
PDF_FILE = "World-Boxing-Ranking-2026-July.pdf"
OUT_CSV  = "World_Boxing_Rankings.csv"
