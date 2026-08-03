"""Entry point.

usage: python3 script.py <input.pdf> [output.csv]
output.csv defaults to the pdf's name with a .csv extension
"""
import sys
from pathlib import Path

from pipeline import run


def main(argv=None):
    argv = sys.argv if argv is None else argv
    pdf_path = argv[1] if len(argv) > 1 else "World_wom_Champs2023.pdf"
    out_csv  = argv[2] if len(argv) > 2 else Path(pdf_path).with_suffix(".csv").name

    if not Path(pdf_path).exists():
        sys.exit(f"no such file: {pdf_path}\n"
                 f"usage: python3 {Path(argv[0]).name} <input.pdf> [output.csv]")

    run(pdf_path, out_csv)


if __name__ == "__main__":
    main()
