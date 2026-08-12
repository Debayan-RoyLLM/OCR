"""Page loop, row assembly, and CSV output."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import fitz  # pip install pymupdf
import pandas as pd

from audit import audit, audit_relays, seconds, severity
from config import (ALL_FIELDS, CORE_FIELDS, DPI, DROP_BLANK, DROP_BY_JUDGE,
                    FIELDS, FILL_BACK, KEEP_UNCHOSEN, KEPT_BY_JUDGE,
                    LLM_HEADERS, RELAY_FIELDS, RETRY_ON_AUDIT, RETRY_TEMP_MAX,
                    RETRY_TEMP_STEP, TRIAGE_FAILED, WORKERS)
from llm import extract_page, llm_headers, page_png_b64, usage_summary
from log import collected, log, replay
from triage import decide, probe


class Read(NamedTuple):
    """One page's answer: what the model said, what we kept, what the audit
    thought of it."""
    d: dict            # the whole extraction, or None for a page classed 'other'
    rows: list         # result entries that name somebody
    legs: list         # relay legs that name somebody
    warns: list        # what the audit complained about

    @property
    def empty(self):
        return not self.rows and not self.legs


class Page(NamedTuple):
    """A page after triage: why it was kept or dropped, and its answer."""
    no: int
    keep: bool
    why: str
    read: Read = None
    error: str = None


def extract_pdf(pdf_path, only=None):
    """Walk the PDF and return (result rows, relay-leg rows, stats).

    `only` is an iterable of 1-based page numbers, or None for the whole file
    (script.py --pages).

    WORKERS pages are read at once, since every call is spent waiting on the
    network. Three things make that safe: PyMuPDF is not thread-safe so the
    document is only ever touched under `doc_lock`; each page's output is
    captured and replayed in page order; and nothing raises out of one_page, so
    a bad page is one dead page rather than a dead run.
    """
    doc = fitz.open(pdf_path)
    doc_lock = threading.Lock()
    buffered = max(1, WORKERS) > 1

    def one_page(i):
        """Triage then extract page i. Never raises."""
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

    every = range(1, doc.page_count + 1)
    pages = [i for i in (every if only is None else only) if i in every]
    if only is not None:
        log.info(f"reading {len(pages)} of {doc.page_count} pages: {pages}")

    all_rows, all_legs = [], []
    failed, dropped, skipped, flagged = [], [], [], []
    audited = {}                         # page -> what the audit still complained of
    reasons = {}
    layout = None                        # the model's column names, decided once
    stopped_early = False
    # (date_iso, date_raw) of the last block that printed a date. An event whose
    # rows run past the bottom of a page resumes at the top of the next one with
    # no date on it, so it inherits this. Kept HERE, in the loop that runs in
    # page order, and not in the workers, which do not.
    carry = (None, None)

    def in_page_order(numbers):
        """One page at a time in page order, WORKERS of them in flight.

        `yield from` and not `list(...)`: map hands pages back in submission
        order as they finish, so yielding reports page 1 the moment page 1 is
        done. Wrapping it in a list would wait for the last page first.

        WORKERS=1 skips the pool. A pool of one still runs ahead of the report,
        and with capture off its output would print over it."""
        if not buffered:
            yield from map(one_page, numbers)
            return
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            yield from pool.map(one_page, numbers)

    # one_page cannot raise, but the merging below can. Whatever was extracted
    # before a failure is still returned and still written.
    try:
        for page, said in in_page_order(pages):
            replay(said)
            reasons.setdefault(page.why, []).append(page.no)

            if not page.keep:
                dropped.append(page.no)      # never billed for extraction
                continue
            # `is not None`: str(RuntimeError()) is "", and a falsy error would
            # fall through to page.read.d on a page that has no read at all.
            if page.error is not None:
                failed.append(page.no)
                continue
            if page.read.d is None:
                skipped.append(page.no)
                continue
            if page.read.empty:
                continue
            if page.read.warns:
                flagged.append(page.no)
                audited[page.no] = list(page.read.warns)

            rows, legs, d = page.read.rows, page.read.legs, page.read.d

            # The event and its date belong to the BLOCK, and unpack has already
            # put them on the row. Only the meet name and the provenance are
            # page-wide. A row still without a date came off a block continued
            # from the previous page, which prints none: it inherits `carry`.
            for r in rows + legs:
                r.update(event=d["event"], date_source=d["date_source"],
                         _page=page.no)
                if not r.get("date"):
                    r["date"], r["date_raw"] = carry
            carry = last_dated(d) or carry
            all_rows += rows
            all_legs += legs

            # The first page carrying data names the columns of BOTH files.
            # Re-rendered rather than carried out of the worker: keeping an
            # image per result would pin the whole document in memory, and a
            # render is milliseconds. One extra API call, then never again.
            if layout is None:
                with doc_lock:
                    png = page_png_b64(doc[page.no - 1], DPI)
                samples = sample_values(rows + legs)
                layout = resolve_layout(
                    llm_headers(png, samples) if LLM_HEADERS else [],
                    shown={f for f, v in samples.items() if v})
                log.info(f"  columns (from p{page.no}): " +
                         ", ".join(layout[1][f] for f in layout[0]))

            seen = list(dict.fromkeys(f"E{r['event_no']}" for r in rows + legs))
            log.info(f"p{page.no:>3}: {len(rows)} rows, {len(legs)} legs | "
                     f"{' '.join(seen)} | ranks={[r['rank'] for r in rows]}")
    except Exception as e:
        log.warning(f"\n! the page loop stopped early — {type(e).__name__}: {e}")
        log.warning(f"! keeping the {len(all_rows)} rows and {len(all_legs)} "
                    f"legs already extracted")
        stopped_early = True
    finally:
        doc.close()

    stats = {"failed": failed, "dropped": dropped, "skipped": skipped,
             "flagged": flagged, "audited": audited, "reasons": reasons,
             "stopped_early": stopped_early,
             "layout": layout or resolve_layout([])}
    return all_rows, all_legs, stats


# What a block's rows inherit from its heading. The date is here rather than at
# page level because ONE page carries several events, each with its own date on
# a multi-day meet — and because a continued block prints none, which is what
# extract_pdf's `carry` fills in afterwards.
HEADING = ("event_no", "discipline", "gender", "age_group", "phase")

RESULT_KEYS = ("rank", "name", "team", "time_raw", "status", "remark",
               "record_set")
LEG_KEYS = ("rank", "team", "leg", "swimmer")

# `status` is not among them: Q, R and DNS belong to the TEAM, and the team's
# own row in `results` already carries it. unpack() copies it across rather than
# asking the model for it a second time — one fewer thing to read wrong, and the
# two files cannot end up disagreeing about who qualified.


def unpack(d):
    """The blocks flattened into two row lists, each row carrying its block's
    heading, minus the entries that name nobody.

    Block order is page order, so the lists come out top to bottom — which is
    what lets extract_pdf fill a continued block's date from the page before."""
    rows, legs = [], []
    for b in d.get("blocks") or []:
        head = {k: b.get(k) for k in HEADING}
        head["date"], head["date_raw"] = b.get("date_iso"), b.get("date_raw")

        for r in b.get("results") or []:
            if not (r.get("name") or r.get("team")):
                continue
            rows.append({**head, **{k: r.get(k) for k in RESULT_KEYS}})

        status = {(r.get("team") or "").strip(): r.get("status")
                  for r in b.get("results") or []}
        for l in b.get("relay_legs") or []:
            if not l.get("swimmer"):
                continue
            leg = {**head, **{k: l.get(k) for k in LEG_KEYS}}
            leg["status"] = status.get((leg.get("team") or "").strip())
            legs.append(leg)

    return rows, legs


def last_dated(d):
    """(date_iso, date_raw) of the LAST block on the page that printed a date,
    which is what the next page's continued block inherits. None if no block on
    the page printed one, and then the page before it still stands."""
    got = None
    for b in d.get("blocks") or []:
        if b.get("date_iso") or b.get("date_raw"):
            got = (b.get("date_iso"), b.get("date_raw"))
    return got


def check(page_no, d, rows, legs, quiet=False):
    """Both audits read the BLOCKS, not the flattened rows: every check is per
    event, and flattening is exactly what loses the event boundaries."""
    blocks = d.get("blocks") or []
    warns = []
    if rows:
        warns += audit(page_no, blocks, quiet=quiet)
    if legs:
        warns += audit_relays(page_no, blocks, quiet=quiet)
    return warns


def read_page(page_no, png) -> Read:
    """Extract one page, check the answer, and ask again if it does not add up.

    The audit knows exactly what is short, so the complaint is handed back and
    the model re-reads the page. Only failing pages pay. A retry is kept only if
    it is better by WEIGHT, not by count — fixing the arithmetic outranks
    picking up a couple of cosmetic quibbles on the way.
    """
    d = extract_page(png, page_no=page_no)
    if d["page_type"] == "other":
        log.info(f"p{page_no}: model classified it 'other' — nothing to extract")
        return Read(None, [], [], [])

    rows, legs = unpack(d)
    if not rows and not legs:
        log.info(f"p{page_no}: classified {d['page_type']} but returned nothing")
        return Read(d, [], [], [])

    # Quiet until the end: only the surviving read gets printed.
    best = Read(d, rows, legs, check(page_no, d, rows, legs, quiet=True))

    tried = []                   # what each re-read so far still got wrong
    for attempt in range(1, RETRY_ON_AUDIT + 1):
        if not best.warns:
            break
        log.info(f"  ...p{page_no} did not add up — reading it again "
                 f"({attempt} of {RETRY_ON_AUDIT})")
        try:
            d2 = extract_page(png, retry_note(best.warns, attempt, tried),
                              page_no=page_no, temperature=retry_temp(attempt))
            rows2, legs2 = unpack(d2)
        except Exception as e:
            log.warning(f"  ! retry failed ({e}) — keeping the best answer so far")
            break

        warns2 = check(page_no, d2, rows2, legs2, quiet=True)
        tried.append(list(warns2))
        if not (rows2 or legs2) or severity(warns2) >= severity(best.warns):
            log.info(f"  no better ({len(warns2)} complaints, weight "
                     f"{severity(warns2)} vs {severity(best.warns)}) — "
                     f"keeping the earlier read")
            continue
        log.info(f"  better: weight {severity(best.warns)} -> {severity(warns2)}"
                 f"  ({len(best.legs)} legs -> {len(legs2)})")
        best = Read(d2, rows2, legs2, warns2)

    for w in best.warns:
        log.warning(f"  ! p{page_no}: {w}")
    return best


def retry_temp(attempt):
    """How much freedom re-read number `attempt` gets. The first gets none."""
    return min(RETRY_TEMP_STEP * (attempt - 1), RETRY_TEMP_MAX)


def retry_note(warns, attempt=1, tried=()):
    """The audit's own words, handed back to the model.

    `attempt` and `tried` keep each re-read a different question. The cache key
    is the instruction text, so a note identical to the last one would buy back
    the identical answer and fix nothing."""
    which = "YOUR FIRST ANSWER" if attempt == 1 else "YOUR BEST ANSWER SO FAR"
    note = ("\n\n" + "=" * 70 + "\n"
            f"{which} FOR THIS PAGE WAS CHECKED AND IT DOES NOT ADD UP:\n\n"
            + "\n".join(f"  - {w}" for w in warns)
            + "\n\nRead the page again from the beginning and return the COMPLETE\n"
              "answer, not a patch. The complaints above are arithmetic, not\n"
              "opinion — a race is ordered BY TIME, so they follow from the page\n"
              "itself. The usual causes, in order of likelihood:\n\n"
              "  - a swimmer ranked behind another but faster: one digit of one\n"
              "    of those two times was misread. Re-read both times.\n"
              "  - two swimmers on the same time with different ranks: they tied,\n"
              "    and the page prints the rank ONCE, blank on the second row.\n"
              "    Both get the printed rank.\n"
              "  - a rank with no time, or a row with neither rank nor status:\n"
              "    an annotation line (NMR, a DSQ reason) was read as a row. It\n"
              "    belongs to the row above it, in record_set or remark.\n"
              "  - a relay team short of swimmers: a comma inside the members\n"
              "    line was missed.\n\n"
              "Do NOT invent anything to make the numbers balance: every entry\n"
              "must be printed on the page, and a rank must be transcribed as\n"
              "printed even where that leaves a gap.\n")
    if tried:
        note += (f"\nThis is re-read {attempt}. Re-read {len(tried)} did not fix "
                 "it either — it came back with:\n\n"
                 + "\n".join(f"  - {w}" for w in tried[-1])
                 + "\n\nSo do not simply repeat that reading. Work the page a "
                   "different way\nthan you did last time — read the times column "
                   "on its own, top to\nbottom, and check that it never goes "
                   "backwards; then read the rank\ncolumn on its own and copy "
                   "every digit exactly as printed, including\nthe blanks and the "
                   "numbers a tie skips.\n")
    return note


def sample_values(records, per_field=3):
    """A few real values per field, for the header call to name columns from."""
    return {f: list(dict.fromkeys(
                str(r[f]) for r in records if r.get(f) not in (None, "")))[:per_field]
            for f in ALL_FIELDS}


def clean_header(header):
    """A tidy snake_case column name, or None if what came back is plainly a
    value off the page — "38th_national_games_2025" is an `event`,
    not a header. None falls back to the field name (see resolve_layout)."""
    h = re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")
    if not h or not h[0].isalpha():
        return None
    if len(h) > 25 or h.count("_") > 2:      # long or many-worded = a value
        return None
    return h


def resolve_layout(chosen, shown=()):
    """The model's picks -> (columns it chose, {field: header}, what it saw).

    WHICH columns and what they are CALLED are two decisions; only the second is
    second-guessed here. A bad header costs the name, never the column.

    `shown` is the fields that actually held a value on the one page the model
    judged from. It rides along because finalize() has to tell a field the model
    DECIDED against from one it never had the chance to see."""
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
    return fields, headers, set(shown)


def finalize(df, layout, fields):
    """Settle the model's column choice against the finished data.

    Two different corrections, and the difference matters:

      - a column it KEPT that turns out blank in every row is dropped; there was
        nothing to write.
      - a column it LEFT OUT comes back only if the page it judged from did not
        show that field. Then the omission was ignorance and page 40 would lose
        real data. If the page DID show it and the model still left it out, that
        was a judgement about relevance, and it stands.

    So the model decides the columns off what is on the page, and this only
    covers what the page could not tell it."""
    chosen, headers, shown = layout
    chosen = [f for f in chosen if f in fields]

    def filled(c):
        if c not in df.columns:
            return False
        col = df[c]
        return bool(col.notna().any() and (col.astype("string").str.strip() != "").any())

    keep = [f for f in chosen if filled(f)]
    empty = [f for f in chosen if f not in keep]

    # A column identical to an earlier one says nothing new — except in the core,
    # where it is a coincidence of the data. On a relay page `name` is null and
    # `team` is printed twice, so the two name columns can come out equal;
    # dropping `team` would delete the answer the file exists to record.
    same = list(dict.fromkeys(          # a field equal to two others, listed twice
        b for i, a in enumerate(keep) for b in keep[i + 1:]
        if b not in CORE_FIELDS and df[a].equals(df[b])))
    keep = [f for f in keep if f not in same]

    # A left-out field comes back when the layout page never showed it and
    # FILL_BACK of the finished rows hold a value — which is what keeps `remark`
    # on a document whose first page happens to have nothing disqualified on it.
    # The FILL_BACK share is there because bleed from a neighbouring column is
    # sporadic while a column the page simply did not reach is systematic.
    #
    # A field the page DID show is not rescued: the model saw the values and
    # said no. CORE_FIELDS is the exception, being the handful without which a
    # row cannot be read or traced at all.
    left_out = {f: int(df[f].notna().sum()) for f in fields
                if f not in chosen and filled(f)}
    enough = max(1, int(len(df) * FILL_BACK))
    back = [f for f in left_out
            if f in CORE_FIELDS or KEEP_UNCHOSEN
            or (f not in shown and left_out[f] >= enough)]
    for f in back:                               # back into its FIELDS position
        before = [g for g in fields[:fields.index(f)] if g in keep]
        keep.insert(keep.index(before[-1]) + 1 if before else 0, f)

    if empty: log.info(f"  dropped, empty in every row: {[headers[f] for f in empty]}")
    if same:  log.info(f"  dropped, duplicate column:   {[headers[f] for f in same]}")
    for f in back:
        why = ("it identifies the row" if f in shown or f in CORE_FIELDS
               else "the model's page did not show it")
        log.info(f"  kept back, {why}: {f} ({left_out[f]} rows)")
    dropped = {f: n for f, n in left_out.items() if f not in back}
    if dropped:
        log.info("  left out by the model, later pages hold values: "
                 + ", ".join(f"{f} ({n}{', it saw this field' if f in shown else ''})"
                             for f, n in dropped.items()))
    return keep, {f: headers[f] for f in keep}


ISO = r"\d{4}-\d{2}-\d{2}"


def clean_dates(df):
    """Keep what is already ISO, re-parse the rest from date_raw, blank whatever
    neither yields — a malformed date must not reach the CSV looking official."""
    iso = df["date"].astype("string").str.strip()
    good = iso.str.fullmatch(ISO).fillna(False)

    salvaged = pd.to_datetime(df["date_raw"].where(~good), errors="coerce",
                              dayfirst=True, format="mixed")
    df["date"] = iso.where(good, salvaged.dt.strftime("%Y-%m-%d")).astype("string")

    lost = int((~good & df["date"].isna()).sum())
    if lost:
        log.warning(f"! {lost} rows had a date the model returned in no usable format")
    return df


# Both tables are built the same way and differ only in which columns are text.
TEXT_COLS = {
    "results": ("event", "discipline", "gender", "age_group", "phase", "name",
                "team", "time_raw", "status", "remark", "date_raw", "date_source"),
    "relays":  ("event", "discipline", "gender", "phase", "team", "swimmer",
                "status", "date_raw", "date_source"),
}


def build_table(records, kind):
    df = pd.DataFrame(records)
    for c in TEXT_COLS[kind]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    df = clean_dates(df)

    # Nullable Int64 throughout: a DNS has no rank and a relay has no leg for a
    # team that did not start, and plain int cannot hold that without turning
    # every rank on the page into a float.
    for c in ("event_no", "rank", "leg"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

    # Both tables carry it — the relays' copied off the team's result row — so
    # "dns" and "DNS" cannot end up as two different values across the two files.
    if "status" in df.columns:
        df["status"] = df["status"].str.upper()

    if kind == "results":
        # "1:54.80" -> 114.80. From audit.seconds, so the column in the CSV and
        # the number the audit compared ranks against cannot disagree.
        df["time_sec"] = df["time_raw"].map(seconds).astype("Float64")
        if "record_set" in df.columns:
            df["record_set"] = df["record_set"].astype("boolean")
        return df.sort_values(["_page", "event_no", "rank"], na_position="last")

    return df.sort_values(["_page", "event_no", "rank", "leg"],
                          na_position="last")


def write_csv(df, layout, fields, path, noun):
    """Settle the columns against the finished data, write, and say what went in.
    Both files go out through here so they cannot end up formatted unalike.

    Returns the frame AS WRITTEN — same columns, same order, same names as the
    file."""
    log.info("")
    fields, headers = finalize(df, layout, fields)
    out = df[fields].rename(columns=headers)
    out.to_csv(path, index=False)
    log.info(f"{len(out)} {noun} -> {path}")
    log.info("header: " + ", ".join(headers[f] for f in fields))
    return out


def write_audit(stats, out_csv):
    """The audit's verdict as data rather than scrollback: every page that still
    did not add up after its retries, one row per complaint, joinable to either
    CSV on the page column. Pages that errored outright are listed too."""
    rows = [{"page": p, "weight": getattr(w, "weight", 1), "complaint": str(w)}
            for p, warns in sorted(stats["audited"].items()) for w in warns]
    rows += [{"page": p, "weight": None, "complaint": "extraction failed"}
             for p in stats["failed"]]
    if not rows:
        return None

    path = Path(out_csv).with_name(Path(out_csv).stem + "_audit.csv")
    pd.DataFrame(rows).sort_values(["page", "weight"], ascending=[True, False],
                                   na_position="first").to_csv(path, index=False)
    log.warning(f"{len(rows)} unresolved complaints on "
                f"{len({r['page'] for r in rows})} pages -> {path}")
    return path


def run(pdf_path, out_csv, only=None):
    """Read the PDF and write the CSVs, for a notebook as much as for the CLI.

    Returns (results df, relays df, stats). The frames are exactly what went
    into the files, so run(...)[0] and pd.read_csv(out_csv) agree. Either is
    None when that file had nothing to write; stats is always a dict."""
    log.info(f"reading {pdf_path} -> {out_csv}")
    all_rows, all_legs, stats = extract_pdf(pdf_path, only=only)
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

    if not all_rows and not all_legs:
        log.warning("No rows extracted.")
        write_audit(stats, out_csv)
        return None, None, stats

    df = bf = None
    if all_rows:
        # The summary reads the table BEFORE write_csv renames it — `team` here
        # may be `state` in the file.
        table = build_table(all_rows, "results")
        df = write_csv(table, stats["layout"], FIELDS, out_csv, "rows")
        log.info(f"events: {table['event_no'].nunique()} | "
                 f"teams: {table['team'].nunique()} | "
                 f"dates: {sorted(table['date'].dropna().unique())}")

    # A relay leg is one row per swimmer, a result one per finishing place:
    # different shapes, so a separate file rather than four columns null on
    # every individual event.
    if all_legs:
        relays_csv = Path(out_csv).with_name(Path(out_csv).stem + "_relays.csv")
        btable = build_table(all_legs, "relays")
        bf = write_csv(btable, stats["layout"], RELAY_FIELDS, relays_csv, "relays")
        log.info(f"relay teams: {btable.groupby(['_page', 'event_no']).ngroups} "
                 f"blocks, {len(btable)} legs")

    log.info("")
    write_audit(stats, out_csv)
    if stats["flagged"]: log.warning(f"PAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  log.warning(f"pages that errored: {stats['failed']}")
    if stats["stopped_early"]:
        log.warning("! this run stopped early — the output above is partial")
    return df, bf, stats
