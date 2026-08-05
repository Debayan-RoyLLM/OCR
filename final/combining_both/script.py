"""Entry point.

usage: python3 script.py [-v|-q] [--pages 3,7,12-15] <input.pdf> [output.csv]
output.csv defaults to the pdf's name with a .csv extension

  -v       say everything
  -q       warnings only — the pages that did not add up
  --pages  read only these pages; every page costs an API call

CSVs are written to output/ under the directory you run from.
"""

__author__ = "Debayan"

import sys
from pathlib import Path

import log
from pipeline import run

USAGE = "usage: python3 {} [-v|-q] [--pages 3,7,12-15] <input.pdf> [output.csv]"


def parse_pages(spec):
    """"3,7,12-15" -> [3, 7, 12, 13, 14, 15]. Order and repeats do not matter."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part.lstrip("-"):
                lo, hi = (int(x) for x in part.split("-", 1))
                out += range(lo, hi + 1)
            else:
                out.append(int(part))
        except ValueError:
            raise SystemExit(f"--pages: cannot read {part!r}. Expected some of "
                             f"3, 7, 12-15 separated by commas.") from None
    if not out:
        raise SystemExit("--pages: no pages given")
    return sorted(set(out))


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    verbosity = 0                       # read before anything else can log

    for flag, level in (("-v", 1), ("--verbose", 1), ("-q", -1), ("--quiet", -1)):
        if flag in argv:
            argv.remove(flag)
            verbosity = level
    log.setup(verbosity)

    only = None
    if "--pages" in argv:
        i = argv.index("--pages")
        if i + 1 >= len(argv):
            raise SystemExit("--pages needs a value, e.g. --pages 3,7,12-15")
        only = parse_pages(argv[i + 1])
        del argv[i:i + 2]

    pdf_path = Path(argv[1] if len(argv) > 1 else "World_wom_Champs2023.pdf")
    if not pdf_path.exists():
        sys.exit(f"no such file: {pdf_path}\n" + USAGE.format(Path(argv[0]).name))

    # The standings, the bouts and the audit all land in output/, beside where
    # you ran from. An output path that names a directory is left alone; only a
    # bare filename is placed in output/.
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    if len(argv) > 2:
        given = Path(argv[2])
        out_csv = given if given.parent != Path(".") else output_dir / given.name
    else:
        out_csv = output_dir / pdf_path.with_suffix(".csv").name

    run(str(pdf_path), str(out_csv), only=only)


if __name__ == "__main__":
    main()
