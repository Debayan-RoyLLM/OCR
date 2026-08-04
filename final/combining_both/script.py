"""Entry point.

usage: python3 script.py [-v|-q] <input.pdf> [output.csv]
output.csv defaults to the pdf's name with a .csv extension

  -v  say everything, including what would normally be held back
  -q  warnings only — the pages that did not add up, and nothing else
"""
import sys
from pathlib import Path

import log
from pipeline import run


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    # Read before anything else logs: a flag that arrives after the first
    # message has already missed its job.
    verbosity = 0
    for flag, level in (("-v", 1), ("--verbose", 1), ("-q", -1), ("--quiet", -1)):
        if flag in argv:
            argv.remove(flag)
            verbosity = level
    log.setup(verbosity)

    pdf_path = argv[1] if len(argv) > 1 else "World_wom_Champs2023.pdf"
    out_csv  = argv[2] if len(argv) > 2 else Path(pdf_path).with_suffix(".csv").name

    if not Path(pdf_path).exists():
        sys.exit(f"no such file: {pdf_path}\n"
                 f"usage: python3 {Path(argv[0]).name} [-v|-q] <input.pdf> [output.csv]")

    run(pdf_path, out_csv)


if __name__ == "__main__":
    main()
