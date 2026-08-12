"""Many documents, one after another — from a folder, or from a list of links.

pipeline.run() reads ONE document: it makes one header call, settles one set of
columns against that document's own rows, and writes one set of CSVs. That is
per-document on purpose — two federations name the same field differently, and
one layout stretched over both would fit neither. So a batch is a loop over
run(), not a bigger version of it, and every PDF keeps its own columns.

Documents are read one at a time. Pages inside a document already run
WORKERS-wide (config.WORKERS); reading several documents at once as well would
put WORKERS x documents in flight, which is a rate limit nobody chose. Widen
OCR_WORKERS if you want more concurrency — that is the one knob, and it stays
honest.

Nothing raises out of a single document, the same bargain one_page makes with
the page loop: a corrupt PDF or a dead link costs you that one, not the forty
behind it.
"""
from pathlib import Path
from urllib.parse import urlparse

import fetch
import llm
from log import log
from pipeline import run


def find_pdfs(folder, recursive=False) -> list:
    """Every PDF under `folder`, in a stable order.

    Matched on the lowercased suffix rather than a "*.pdf" glob, which on Linux
    would walk straight past a file named .PDF."""
    root = Path(folder)
    walk = root.rglob("*") if recursive else root.glob("*")
    return sorted((p for p in walk if p.is_file() and p.suffix.lower() == ".pdf"),
                  key=lambda p: str(p).lower())


def _unique(pairs) -> list:
    """Preferred output stems made unique, in order.

    Each pair is (stem, prefix). Two documents can want the same name — a
    `results.pdf` in two subfolders, or on two different sites — and with one
    output directory the second would silently overwrite the first, losing a
    whole document without saying so. The clashing one takes its prefix
    instead; a counter settles the rest.
    """
    taken, out = set(), []
    for stem, prefix in pairs:
        if stem in taken and prefix:
            stem = f"{prefix}_{stem}"
        base, n = stem, 2
        while stem in taken:
            stem = f"{base}_{n}"
            n += 1
        taken.add(stem)
        out.append(stem)
    return out


def out_paths(pdfs, out_dir) -> dict:
    """{pdf: output CSV}. A clashing stem takes its parent folder as a prefix."""
    stems = _unique([(p.stem, p.parent.name) for p in pdfs])
    return {p: Path(out_dir) / f"{s}.csv" for p, s in zip(pdfs, stems)}


def link_out_paths(urls, out_dir) -> dict:
    """{url: output CSV}. Named from the URL's last path segment.

    Same rule as out_paths, with the host standing in for the parent folder —
    that is what distinguishes two sites that both publish a `results.pdf`."""
    stems = _unique([(fetch.stem_of(u), urlparse(u).netloc.replace(":", "_"))
                     for u in urls])
    return {u: Path(out_dir) / f"{s}.csv" for u, s in zip(urls, stems)}


def _rel(p, root) -> str:
    """How a PDF is named in the log: its path below the input folder.

    Not p.name — with -r, two subfolders holding an `alpha.pdf` each would print
    the same banner twice and there would be no telling which one a complaint
    belonged to. out_paths already keeps their CSVs apart; this keeps their
    output apart."""
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


def _add(into: dict, more: dict) -> dict:
    """Fold one document's usage into the batch total."""
    for name, t in more.items():
        run_tot = into.setdefault(name, {"calls": 0, "in": 0, "out": 0, "cached": 0})
        for k, v in t.items():
            run_tot[k] = run_tot.get(k, 0) + v
    return into


def _run_jobs(jobs, out_dir, only, skip_existing) -> dict:
    """The loop a folder and a link list share.

    A job is (key, name, out_csv, obtain), where obtain() produces a local PDF
    path: for a folder that is the file itself, for a link list it is the
    download. Obtaining happens INSIDE the loop, next to the read it feeds, so
    a dead link costs one document at the moment it comes up rather than
    stopping the run before it starts.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    done, failed, skipped, usage, names = {}, {}, [], {}, {}
    llm.usage_reset()                      # anything already spent is not ours

    for i, (key, name, out_csv, obtain) in enumerate(jobs, 1):
        names[key] = name
        if skip_existing and out_csv.exists():
            log.warning(f"[{i}/{len(jobs)}] {name}: already written, skipping")
            skipped.append(key)
            continue

        # The per-document banners are warnings, not info: under -q they are the
        # only thing tying a complaint to the document it came from.
        log.warning(f"\n{'=' * 70}\n[{i}/{len(jobs)}] {name} -> {out_csv.name}\n"
                    f"{'=' * 70}")
        try:
            done[key] = run(str(obtain()), str(out_csv), only=only)
        except Exception as e:
            log.warning(f"! {name} FAILED — {type(e).__name__}: {e}")
            failed[key] = f"{type(e).__name__}: {e}"
        finally:
            _add(usage, llm.usage_reset())

    _summary(done, failed, skipped, usage, names, out_dir)
    return {"done": done, "failed": failed, "skipped": skipped, "usage": usage}


def run_folder(in_dir, out_dir="output", only=None, recursive=False,
               skip_existing=False) -> dict:
    """Read every PDF in a folder and write a set of CSVs for each.

    Returns {"done": {path: (results df, relays df, stats)}, "failed":
    {path: error}, "skipped": [path], "usage": {call kind: totals}} — so a
    notebook can go straight to the frames without re-reading the files.

    `only` is passed through to every document, which is what you want when the
    folder holds one report per event laid out the same way, and not what you
    want otherwise. `skip_existing` resumes a batch that stopped half way.
    """
    pdfs = find_pdfs(in_dir, recursive)
    if not pdfs:
        raise SystemExit(f"no PDFs in {in_dir}" + ("" if recursive else
                                                   " — try -r for subfolders"))
    csvs = out_paths(pdfs, out_dir)
    log.warning(f"{len(pdfs)} PDFs from {in_dir} -> {out_dir}/")
    jobs = [(p, _rel(p, in_dir), csvs[p], (lambda q=p: q)) for p in pdfs]
    return _run_jobs(jobs, out_dir, only, skip_existing)


def run_links(list_path, out_dir="output", only=None, skip_existing=False,
              downloads=None) -> dict:
    """Read every PDF named by a URL in `list_path`, one per line.

    Same return shape as run_folder, keyed by URL rather than by path. Each PDF
    is fetched to config.DOWNLOAD_DIR (or `downloads`) and kept, so a stopped
    run resumes and the source of a flagged page can still be opened.

    A link that 404s, times out, or answers with a login page is recorded in
    "failed" beside a document that merely failed to parse. From here they are
    the same event: this URL produced no rows, and the rest of the list carries
    on regardless.
    """
    urls = fetch.read_links(list_path)
    csvs = link_out_paths(urls, out_dir)
    log.warning(f"{len(urls)} links from {list_path} -> {out_dir}/")
    jobs = [(u, u, csvs[u], (lambda v=u: fetch.download(v, downloads)))
            for u in urls]
    return _run_jobs(jobs, out_dir, only, skip_existing)


def _summary(done, failed, skipped, usage, names, out_dir) -> None:
    """What the batch cost and what needs looking at, once at the end.

    A per-document summary already scrolled past for each one; this is the part
    you read when forty of them have gone by. `names` maps each key — a path or
    a URL — to how it was labelled in the log."""
    def label(k):
        return names.get(k, str(k))

    log.warning(f"\n{'=' * 70}\nBATCH: {len(done)} read, {len(failed)} failed, "
                f"{len(skipped)} skipped")

    rows = sum(len(d) for d, _, _ in done.values() if d is not None)
    legs = sum(len(b) for _, b, _ in done.values() if b is not None)
    log.warning(f"{rows} rows and {legs} relay legs -> {out_dir}/")

    empty = [label(k) for k, (d, b, _) in done.items() if d is None and b is None]
    if empty:
        log.warning(f"read but held nothing to extract: {empty}")

    partial = [label(k) for k, (_, _, s) in done.items() if s["stopped_early"]]
    if partial:
        log.warning(f"! STOPPED EARLY, output is partial: {partial}")

    flagged = {label(k): s["flagged"] for k, (_, _, s) in done.items() if s["flagged"]}
    if flagged:
        log.warning("\nPAGES TO REVIEW — see each document's _audit.csv:")
        for name, pages in flagged.items():
            log.warning(f"  {name}: {pages}")

    if failed:
        log.warning("\nDOCUMENTS THAT FAILED OUTRIGHT:")
        for k, why in failed.items():
            log.warning(f"  {label(k)} — {why}")

    log.warning("\ntoken usage for the whole batch:")
    log.warning(llm.usage_summary(usage))
