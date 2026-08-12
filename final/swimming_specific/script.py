"""Entry point.

usage: python3 script.py [options] <input.pdf>     [output.csv]
       python3 script.py [options] <input_folder>  [output_folder]
       python3 script.py [options] <links.csv>     [output_folder]

output.csv defaults to the pdf's name with a .csv extension. Given a FOLDER, or
a .csv/.txt holding one PDF URL per line, every document is read and gets its
own set of CSVs named after it — columns are settled per document, so two
reports that name the same field differently each keep their own heading.
See batch.py, and fetch.py for the links.

  -v       say everything
  -q       warnings only — the pages that did not add up
  --pages  read only these pages; every page costs an API call
  -r       a folder's subfolders too
  -s       skip a document whose CSV is already written, to resume a stopped run

CSVs are written to output/ under the directory you run from.
"""

__author__ = "Debayan"

import sys
from pathlib import Path

import config
import log
from batch import run_folder, run_links
from pipeline import run

USAGE = ("usage: python3 {} [-v|-q] [--pages 3,7,12-15] [-r] [-s] "
         "<input.pdf|folder|links.csv> [output.csv|folder]")


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


def take_flag(argv, *names) -> bool:
    """Strip every spelling of a flag out of argv; True if any of them was there."""
    found = False
    for n in names:
        while n in argv:
            argv.remove(n)
            found = True
    return found


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    verbosity = 0                       # read before anything else can log

    for flag, level in (("-v", 1), ("--verbose", 1), ("-q", -1), ("--quiet", -1)):
        if flag in argv:
            argv.remove(flag)
            verbosity = level
    log.setup(verbosity)

    recursive = take_flag(argv, "-r", "--recursive")
    skip_existing = take_flag(argv, "-s", "--skip-existing")

    only = None
    if "--pages" in argv:
        i = argv.index("--pages")
        if i + 1 >= len(argv):
            raise SystemExit("--pages needs a value, e.g. --pages 3,7,12-15")
        only = parse_pages(argv[i + 1])
        del argv[i:i + 2]

    pdf_path = Path(argv[1] if len(argv) > 1
                    else "downloads/38thng_Day-1_Heat_Result.pdf")
    if not pdf_path.exists():
        sys.exit(f"no such file: {pdf_path}\n" + USAGE.format(Path(argv[0]).name))

    # OpenAI or your own endpoint. Asked here, after the input has been checked,
    # so a mistyped path costs nothing, and before any page is read, because the
    # first thing the pipeline does is spend a call.
    config.choose_provider()

    # The results, the relay legs and the audit all land in output/, beside where
    # you ran from. An output path that names a directory is left alone; only a
    # bare filename is placed in output/.
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Many documents in, a folder out: batch.py names each document's CSVs
    # itself, so the second argument is a directory in both of these branches
    # rather than a file.
    many_out = str(Path(argv[2]) if len(argv) > 2 else output_dir)

    if pdf_path.is_dir():
        run_folder(str(pdf_path), many_out, only=only, recursive=recursive,
                   skip_existing=skip_existing)
        return

    # A .csv or .txt in the input position is a LIST of links, not a document:
    # one PDF URL per line, each fetched and read in turn. See fetch.py.
    if pdf_path.suffix.lower() in (".csv", ".txt"):
        if recursive:
            log.log.warning("! -r means nothing for a link list — ignored")
        run_links(str(pdf_path), many_out, only=only, skip_existing=skip_existing)
        return

    if recursive or skip_existing:
        log.log.warning("! -r and -s only mean something for a folder or a "
                        "link list — ignored")

    if len(argv) > 2:
        given = Path(argv[2])
        out_csv = given if given.parent != Path(".") else output_dir / given.name
    else:
        out_csv = output_dir / pdf_path.with_suffix(".csv").name

    run(str(pdf_path), str(out_csv), only=only)


if __name__ == "__main__":
    main()
