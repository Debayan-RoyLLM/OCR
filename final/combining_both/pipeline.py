"""Page loop, row assembly, and CSV output."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import fitz  # pip install pymupdf
import pandas as pd

from audit import audit, audit_bouts, severity
from config import (ALL_FIELDS, BOUT_FIELDS, CORE_FIELDS, DPI, DROP_BLANK,
                    FIELDS, KEEP_UNCHOSEN, KEPT_BY_JUDGE, DROP_BY_JUDGE,
                    LLM_HEADERS, RETRY_ON_AUDIT, TRIAGE_FAILED, WORKERS)
from llm import extract_page, llm_headers, page_png_b64, usage_summary
from log import collected, log, replay
from triage import decide, probe


class Read(NamedTuple):
    """One page's answer: what the model said, what we kept of it, and what the
    audit thought of that. Named rather than a bare 4-tuple because the retry
    loop compares two of these field by field, and `best[3]` told nobody what
    the third slot held."""
    d: dict            # the whole extraction, or None for a page classed 'other'
    rows: list         # standings entries that name somebody
    bouts: list        # bouts that name somebody
    warns: list        # what the audit complained about

    @property
    def empty(self):
        return not self.rows and not self.bouts


class Page(NamedTuple):
    """A page after triage: why it was kept or dropped, and its answer."""
    no: int
    keep: bool
    why: str
    read: Read = None
    error: str = None


def extract_pdf(pdf_path):
    """Walk the PDF and return (standings rows, bout rows, stats).

    Pages are independent and every call is spent waiting on the network, so
    WORKERS of them are read at once. Three things make that safe:

      * PyMuPDF is not thread-safe, so every touch of the document happens under
        `doc_lock` — rendering is milliseconds against a call of seconds, and
        serialising it costs nothing;
      * each page's output is captured while it works and replayed when its turn
        comes, so a parallel run reads exactly like a serial one;
      * pool.map yields in page order AS PAGES FINISH, and the loop below
        consumes it lazily. Page 1 is reported the moment page 1 is done, not
        when the document is. A page that throws is one dead page, not a dead
        run — nothing raises out of one_page.

    With WORKERS=1 nothing is captured at all: output goes straight to the
    terminal line by line, which is what you want when a page is misbehaving and
    you would rather watch it than wait for it.
    """
    doc = fitz.open(pdf_path)
    doc_lock = threading.Lock()
    buffered = max(1, WORKERS) > 1

    def one_page(i):
        """Triage then extract page i. Never raises: a page that dies takes its
        own rows with it and nothing else."""
        with collected(buffered) as said:
            try:
                with doc_lock:
                    blank, judge_png = probe(doc[i - 1])
                keep, why = decide(blank, judge_png)
            except Exception as e:
                log.warning(f"p{i}: FAILED in triage — {e}")
                return Page(i, True, TRIAGE_FAILED, error=str(e)), said

            if not keep:
                return Page(i, False, why), said

            try:
                with doc_lock:
                    png = page_png_b64(doc[i - 1], DPI)
                return Page(i, True, why, read=read_page(i, png)), said
            except Exception as e:
                log.warning(f"p{i}: FAILED — {e}")
                return Page(i, True, why, error=str(e)), said

    all_rows, all_bouts = [], []
    failed, dropped, skipped, flagged = [], [], [], []
    reasons = {}
    layout = None                        # the model's column names, decided once

    def in_page_order(numbers):
        """One page at a time in page order, but WORKERS of them in flight.

        `yield from pool.map` is the whole trick: map hands back finished pages
        in the order they were submitted, and yielding them keeps the loop below
        consuming one at a time. Wrapping it in `list()` instead would wait for
        the last page before printing the first.

        WORKERS=1 skips the pool altogether. A pool of one still starts the next
        page while this one is being reported, and since nothing is captured at
        that setting its output would print over the report — plain `map` reads
        the same and cannot get ahead of itself."""
        if not buffered:
            yield from map(one_page, numbers)
            return
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            yield from pool.map(one_page, numbers)

    for page, said in in_page_order(range(1, doc.page_count + 1)):
        replay(said)
        reasons.setdefault(page.why, []).append(page.no)

        if not page.keep:
            dropped.append(page.no)      # never billed for extraction
            continue
        if page.error:
            failed.append(page.no)
            continue
        if page.read.d is None:
            skipped.append(page.no)
            continue
        if page.read.empty:
            continue
        if page.read.warns:
            flagged.append(page.no)

        rows, bouts, d = page.read.rows, page.read.bouts, page.read.d

        # A page can stack several weight classes, so division is a per-row answer.
        # The page-level one is only a fallback for the single-category sheets.
        for r in rows + bouts:
            r.update(event=d["event"], date=d["date_iso"], date_raw=d["date_raw"],
                     date_source=d["date_source"],
                     division=(r.get("division") or d["division"]), _page=page.no)
        for r in rows:
            r["page_type"] = d["page_type"]
        all_rows += rows
        all_bouts += bouts

        # First page that actually carried data names the columns of BOTH files —
        # a page the filters admitted but that turned out to be prose would name
        # them badly. It gets that page's image again (one render, no call) plus
        # its finished rows, so the model can see what each field really holds.
        # One extra call, then never asked again.
        if layout is None:
            with doc_lock:
                png = page_png_b64(doc[page.no - 1], DPI)
            layout = resolve_layout(
                llm_headers(png, sample_values(rows + bouts)) if LLM_HEADERS else [])
            log.info(f"  columns (from p{page.no}): " +
                     ", ".join(layout[1][f] for f in layout[0]))

        seen = list(dict.fromkeys(r["division"] for r in rows + bouts))
        log.info(f"p{page.no:>3}: {len(rows)} rows, {len(bouts)} bouts | "
                 f"{d['page_type']} | {' + '.join(map(str, seen))} "
                 f"| ranks={[r['rank'] for r in rows]}")

    doc.close()
    stats = {"failed": failed, "dropped": dropped, "skipped": skipped,
             "flagged": flagged, "reasons": reasons,
             "layout": layout or resolve_layout([])}
    return all_rows, all_bouts, stats


def unpack(d):
    """The two arrays, minus the entries that name nobody."""
    return ([r for r in d["standings"] if r["name_short"] or r["name"]],
            [b for b in d["bouts"] if b["boxer_a"] or b["boxer_b"]])


def check(page_no, d, rows, bouts, quiet=False):
    warns = []
    if rows:
        warns += audit(page_no, d, rows, quiet=quiet)
    if bouts:
        warns += audit_bouts(page_no, bouts, d["boxers_drawn"],
                             d["rounds_printed"], quiet=quiet)
    return warns


def read_page(page_no, png) -> Read:
    """Extract one page, check the answer, and ask again if it does not add up.

    The audit already knows exactly what is short — "10 boxers needs 9 bouts, got
    7" — so the cheapest fix is to hand that complaint back and let the model
    re-read the page. Only pages that fail pay for the second call, and the
    retry is kept only if it is actually better than what it replaces — better
    by weight, not by count, so fixing the arithmetic outranks picking up a
    couple of cosmetic quibbles on the way.
    """
    d = extract_page(png, page_no=page_no)
    if d["page_type"] == "other":
        log.info(f"p{page_no}: model classified it 'other' — nothing to extract")
        return Read(None, [], [], [])

    rows, bouts = unpack(d)
    if not rows and not bouts:
        log.info(f"p{page_no}: classified {d['page_type']} but returned nothing")
        return Read(d, [], [], [])

    # Quiet until the end: only whatever survives as the best read gets printed.
    best = Read(d, rows, bouts, check(page_no, d, rows, bouts, quiet=True))

    for attempt in range(1, RETRY_ON_AUDIT + 1):
        if not best.warns:
            break
        log.info(f"  ...p{page_no} did not add up — reading it again "
                 f"({attempt} of {RETRY_ON_AUDIT})")
        try:
            d2 = extract_page(png, retry_note(best.warns), page_no=page_no)
            rows2, bouts2 = unpack(d2)
        except Exception as e:
            log.warning(f"  ! retry failed ({e}) — keeping the best answer so far")
            break

        warns2 = check(page_no, d2, rows2, bouts2, quiet=True)
        if not (rows2 or bouts2) or severity(warns2) >= severity(best.warns):
            log.info(f"  no better ({len(warns2)} complaints, weight "
                     f"{severity(warns2)} vs {severity(best.warns)}) — "
                     f"keeping the earlier read")
            continue
        log.info(f"  better: weight {severity(best.warns)} -> {severity(warns2)}"
                 f"  ({len(best.bouts)} bouts -> {len(bouts2)})")
        best = Read(d2, rows2, bouts2, warns2)

    for w in best.warns:
        log.warning(f"  ! p{page_no}: {w}")
    return best


def retry_note(warns):
    """The audit's own words, handed back to the model."""
    return ("\n\n" + "=" * 70 + "\n"
            "YOUR FIRST ANSWER FOR THIS PAGE WAS CHECKED AND IT DOES NOT ADD UP:\n\n"
            + "\n".join(f"  - {w}" for w in warns)
            + "\n\nRead the page again from the beginning and return the COMPLETE\n"
              "answer, not a patch. The counts above are arithmetic, not opinion —\n"
              "if you are short of bouts, a whole column or a pair inside one has\n"
              "been missed, most often where byes crowd the first column. Go\n"
              "through that column line by line. Do NOT invent anything to make\n"
              "the numbers balance: every line must be drawn on the page.\n")


def sample_values(records, per_field=3):
    """A few real values per field, for the header call to name columns from."""
    return {f: list(dict.fromkeys(
                str(r[f]) for r in records if r.get(f) not in (None, "")))[:per_field]
            for f in ALL_FIELDS}


def clean_header(header):
    """A header names a column; it is not a cell. Returns a tidy snake_case name,
    or None if the model handed back something that is plainly a value off the
    page — "world_boxing_cup_finals_greater_noida_2025" is an `event`, not a
    header. Rejected names fall back to the field's own name (see resolve_layout)."""
    h = re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")
    if not h or not h[0].isalpha():
        return None
    if len(h) > 25 or h.count("_") > 2:      # long or many-worded = a value
        return None
    return h


def resolve_layout(chosen):
    """Turn the model's picks into (columns it chose, {field: header}).

    The model decides which columns the document gets and what they are called.
    Those are two separate decisions, and only the second one is second-guessed
    here: a header that is really a value off the page is replaced by the
    field's own name, and the column still gets written. Dropping the column
    over its NAME — which is what used to happen — threw away real data because
    the model phrased something badly."""
    fields, headers = [], {}
    for field, header in chosen:
        if field not in ALL_FIELDS or field in headers:
            continue                       # invented, or already named
        name = clean_header(header)
        if name is None:
            name = field
            log.info(f"  header {header!r} looks like a value, not a column name "
                     f"— calling it {field!r}")
        if name in headers.values():        # two fields, one name: keep the first
            continue
        fields.append(field)
        headers[field] = name

    if not fields:                        # LLM_HEADERS off, or the call failed
        fields = list(ALL_FIELDS)
    for f in ALL_FIELDS:
        headers.setdefault(f, f if f not in headers.values() else f"{f}_field")
    return fields, headers


def finalize(df, layout, fields):
    """The model chose the columns from one page; the finished data has the last
    word. A column it kept that turned out blank in every row is dropped, and one
    it left out that turned out to hold values is put back — a guess made on page
    1 must not cost a column of real data on page 40."""
    chosen, headers = layout
    chosen = [f for f in chosen if f in fields]

    def filled(c):
        if c not in df.columns:
            return False
        col = df[c]
        return bool(col.notna().any() and (col.astype("string").str.strip() != "").any())

    keep = [f for f in chosen if filled(f)]
    empty = [f for f in chosen if f not in keep]

    # A column identical to an earlier one in every row says nothing new — except
    # in the core, where being identical is a coincidence of the data, not a sign
    # the column is redundant. On a bracket where the top seed wins every bout
    # `winner` matches `boxer_a` in every row, and dropping it silently deleted
    # the answer the whole file exists to record.
    same = [b for i, a in enumerate(keep) for b in keep[i + 1:]
            if b not in CORE_FIELDS and df[a].equals(df[b])]
    keep = [f for f in keep if f not in same]

    # A field the model left out stays out, even where the extractor put
    # something in it — a column it judged absent from the page is usually
    # absent, and what lands there is junk copied from a neighbouring column.
    # The exception is the core: drop `date` or `name` and the file stops being
    # identifiable, so those come back on their own.
    left_out = {f: int(df[f].notna().sum()) for f in fields
                if f not in chosen and filled(f)}
    back = [f for f in left_out if f in CORE_FIELDS or KEEP_UNCHOSEN]
    for f in back:                               # into its canonical place
        before = [g for g in fields[:fields.index(f)] if g in keep]
        keep.insert(keep.index(before[-1]) + 1 if before else 0, f)

    if empty: log.info(f"  dropped, empty in every row: {[headers[f] for f in empty]}")
    if same:  log.info(f"  dropped, duplicate column:   {[headers[f] for f in same]}")
    if back:  log.info(f"  kept back, identifies the row: {back}")
    dropped = {f: n for f, n in left_out.items() if f not in back}
    if dropped:
        log.info("  NOT WRITTEN, model gave no column but rows hold values: "
                 + ", ".join(f"{f} ({n})" for f, n in dropped.items()))
    return keep, {f: headers[f] for f in keep}


ISO = r"\d{4}-\d{2}-\d{2}"


def clean_dates(df):
    """The model is asked for YYYY-MM-DD but is not constrained to it. Keep what
    is already ISO; re-parse the rest from date_raw; blank whatever neither
    yields, so a malformed date never reaches the CSV looking authoritative."""
    iso = df["date"].astype("string").str.strip()
    good = iso.str.fullmatch(ISO).fillna(False)

    salvaged = pd.to_datetime(df["date_raw"].where(~good), errors="coerce",
                              dayfirst=True, format="mixed")
    df["date"] = iso.where(good, salvaged.dt.strftime("%Y-%m-%d")).astype("string")

    lost = int((~good & df["date"].isna()).sum())
    if lost:
        log.warning(f"! {lost} rows had a date the model returned in no usable format")
    return df


# The two tables are built the same way — strip the text columns, salvage the
# dates, coerce the one numeric column, sort — and differ only in which columns
# those are. Written once so a fix to one cannot miss the other.
TEXT_COLS = {
    "standings": ("event", "division", "page_type", "name", "name_short",
                  "country", "medal", "previous_rank", "date_raw", "date_source"),
    "bouts":     ("event", "division", "round", "boxer_a", "country_a", "boxer_b",
                  "country_b", "winner", "result", "date_raw", "date_source"),
}


def build_table(records, kind):
    df = pd.DataFrame(records)
    for c in TEXT_COLS[kind]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    df = clean_dates(df)

    if kind == "standings":
        df["name"] = df["name"].fillna(df["name_short"])   # fall back to the box text
        df["rank"] = df["rank"].astype("Int64")
        df["points_total"] = pd.to_numeric(df["points_total"], errors="coerce")
        return df.sort_values(["_page", "rank"], na_position="last")

    df["bout_no"] = pd.to_numeric(df["bout_no"], errors="coerce").astype("Int64")
    return df.sort_values(["_page", "bout_no"], na_position="last")


def write_csv(df, layout, fields, path, noun):
    """Settle the columns against the finished data, write, and say what went in.
    Both files go out through here so they can never end up formatted unalike."""
    log.info("")
    fields, headers = finalize(df, layout, fields)
    df[fields].rename(columns=headers).to_csv(path, index=False)
    log.info(f"{len(df)} {noun} -> {path}")
    log.info("header: " + ", ".join(headers[f] for f in fields))
    return df


def run(pdf_path, out_csv):
    log.info(f"reading {pdf_path} -> {out_csv}")
    all_rows, all_bouts, stats = extract_pdf(pdf_path)
    reasons = stats["reasons"]

    log.info("\ntriage: " + " | ".join(f"{k}={len(v)}" for k, v in reasons.items()))
    for reason, line in ((KEPT_BY_JUDGE, "pages the judge sent through"),
                         (DROP_BLANK,    "blank pages, dropped free"),
                         (DROP_BY_JUDGE, "pages the judge turned away")):
        if reasons.get(reason):
            log.info(f"{line}: {reasons[reason]}")
    if stats["skipped"]:
        log.info(f"pages the model classified 'other': {stats['skipped']}")
    if stats["failed"]:
        log.warning(f"pages that errored (paid, no data): {stats['failed']}")

    log.info("\ntoken usage (as reported by the API):")
    log.info(usage_summary())

    if not all_rows and not all_bouts:
        log.warning("No rows extracted.")
        return

    if all_rows:
        df = write_csv(build_table(all_rows, "standings"), stats["layout"],
                       FIELDS, out_csv, "rows")
        log.info(f"divisions: {df['division'].nunique()} | "
                 f"dates: {list(df['date'].unique())}")

    # The bouts of a draw sheet are a different shape from its standings — one
    # row per fight, not per boxer — so they get their own file rather than a
    # column that is null for half the rows.
    if all_bouts:
        bouts_csv = Path(out_csv).with_name(Path(out_csv).stem + "_bouts.csv")
        bf = write_csv(build_table(all_bouts, "bouts"), stats["layout"],
                       BOUT_FIELDS, bouts_csv, "bouts")
        log.info(f"rounds: {[r for r in bf['round'].dropna().unique()]}")

    if stats["flagged"]: log.warning(f"\nPAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  log.warning(f"pages that errored: {stats['failed']}")
