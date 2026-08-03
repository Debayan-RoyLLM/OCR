"""Page loop, row assembly, and CSV output."""
import re
from pathlib import Path

import fitz  # pip install pymupdf
import pandas as pd

from audit import audit, audit_bouts
from config import ALL_FIELDS, BOUT_FIELDS, DPI, FIELDS, LLM_HEADERS
from llm import extract_page, llm_headers, page_png_b64, usage_summary
from triage import decide


def extract_pdf(pdf_path):
    """Walk the PDF and return (standings rows, bout rows, stats). Prints
    progress as it goes."""
    doc = fitz.open(pdf_path)
    all_rows, all_bouts = [], []
    failed, dropped, skipped, flagged = [], [], [], []
    reasons = {}
    layout = None                        # the model's column names, decided once

    for i, page in enumerate(doc, start=1):
        keep, why = decide(page)
        reasons.setdefault(why, []).append(i)
        if not keep:
            dropped.append(i)            # never billed for extraction
            continue

        png = page_png_b64(page, DPI)
        try:
            d = extract_page(png)
        except Exception as e:
            print(f"p{i}: FAILED — {e}")
            failed.append(i)
            continue

        if d["page_type"] == "other":
            print(f"p{i}: model classified it 'other' — nothing to extract")
            skipped.append(i)
            continue

        rows = [r for r in d["standings"] if r["name_short"] or r["name"]]
        bouts = [b for b in d["bouts"] if b["boxer_a"] or b["boxer_b"]]
        if not rows and not bouts:
            print(f"p{i}: classified {d['page_type']} but returned nothing")
            continue

        if rows and audit(i, d, rows):
            flagged.append(i)
        if bouts and audit_bouts(i, bouts, d["boxers_drawn"]):
            flagged.append(i)

        # A page can stack several weight classes, so division is a per-row answer.
        # The page-level one is only a fallback for the single-category sheets.
        for r in rows + bouts:
            r.update(event=d["event"], date=d["date_iso"], date_raw=d["date_raw"],
                     date_source=d["date_source"],
                     division=(r.get("division") or d["division"]), _page=i)
        for r in rows:
            r["page_type"] = d["page_type"]
        all_rows += rows
        all_bouts += bouts

        # First page that actually carried data names the columns of BOTH files —
        # a page the filters admitted but that turned out to be prose would name
        # them badly. Same image, plus its finished rows so the model can see what
        # each field really holds. One extra call, then never asked again.
        if layout is None:
            layout = resolve_layout(
                llm_headers(png, sample_values(rows + bouts)) if LLM_HEADERS else [])
            print(f"  columns (from p{i}): " +
                  ", ".join(layout[1][f] for f in layout[0]))
        seen = list(dict.fromkeys(r["division"] for r in rows + bouts))
        print(f"p{i:>3}: {len(rows)} rows, {len(bouts)} bouts | {d['page_type']} "
              f"| {' + '.join(map(str, seen))} | ranks={[r['rank'] for r in rows]}")

    stats = {"failed": failed, "dropped": dropped, "skipped": skipped,
             "flagged": flagged, "reasons": reasons,
             "layout": layout or resolve_layout([])}
    return all_rows, all_bouts, stats


def sample_values(records, per_field=3):
    """A few real values per field, for the header call to name columns from."""
    return {f: list(dict.fromkeys(
                str(r[f]) for r in records if r.get(f) not in (None, "")))[:per_field]
            for f in ALL_FIELDS}


def table_layout(layout, fields):
    """The columns of one file, in the order the model chose for the whole set."""
    order, headers = layout
    cols = [f for f in order if f in fields]
    return cols, {f: headers[f] for f in cols}


def clean_header(header):
    """A header names a column; it is not a cell. Returns a tidy snake_case name,
    or None if the model handed back something that is plainly a value off the
    page — "world_boxing_cup_finals_greater_noida_2025" is an `event`, not a
    header. Rejected names fall back to the field's own name."""
    h = re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")
    if not h or not h[0].isalpha():
        return None
    if len(h) > 25 or h.count("_") > 2:      # long or many-worded = a value
        return None
    return h


def resolve_layout(chosen):
    """Turn the model's picks into (fields, {field: header}).

    Trusted for naming and ordering, checked for everything else: a field it
    invented or repeated is dropped, and one it forgot is appended under its own
    name. The CSV can gain a better header but can never lose a column."""
    fields, headers = [], {}
    for field, header in chosen:
        header = clean_header(header)
        if (header and field in ALL_FIELDS
                and field not in headers and header not in headers.values()):
            fields.append(field)
            headers[field] = header

    missing = [f for f in ALL_FIELDS if f not in headers]
    if missing and chosen:
        print(f"! model returned no usable header for {missing} — kept as-is")
    for f in missing:
        fields.append(f)
        headers[f] = f if f not in headers.values() else f"{f}_field"
    return fields, headers


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
        print(f"! {lost} rows had a date the model returned in no usable format")
    return df


def build_dataframe(all_rows):
    df = pd.DataFrame(all_rows)
    for c in ("event", "division", "page_type", "name", "name_short",
              "country", "medal", "previous_rank", "date_raw", "date_source"):
        df[c] = df[c].astype("string").str.strip()
    df = clean_dates(df)

    df["name"] = df["name"].fillna(df["name_short"])       # fall back to the box text
    df["rank"] = df["rank"].astype("Int64")
    df["points_total"] = pd.to_numeric(df["points_total"], errors="coerce")
    return df.sort_values(["_page", "rank"], na_position="last")


def build_bouts(all_bouts):
    df = pd.DataFrame(all_bouts)
    for c in ("event", "division", "round", "boxer_a", "country_a", "boxer_b",
              "country_b", "winner", "result", "date_raw", "date_source"):
        df[c] = df[c].astype("string").str.strip()
    df = clean_dates(df)
    df["bout_no"] = pd.to_numeric(df["bout_no"], errors="coerce").astype("Int64")
    return df.sort_values(["_page", "bout_no"], na_position="last")


def run(pdf_path, out_csv):
    print(f"reading {pdf_path} -> {out_csv}")
    all_rows, all_bouts, stats = extract_pdf(pdf_path)
    reasons = stats["reasons"]

    print("\ntriage: " + " | ".join(f"{k}={len(v)}" for k, v in reasons.items()))
    if reasons.get("judge"):
        print(f"pages the gates failed but the judge rescued: {reasons['judge']}")
    if stats["dropped"]:
        print(f"pages dropped before extraction: {stats['dropped']}")
    if stats["skipped"]:
        print(f"pages the model classified 'other': {stats['skipped']}")
    if stats["failed"]:
        print(f"pages that errored (paid, no data): {stats['failed']}")

    print("\ntoken usage (as reported by the API):")
    print(usage_summary())

    if not all_rows and not all_bouts:
        print("No rows extracted.")
        return

    if all_rows:
        df = build_dataframe(all_rows)
        fields, headers = table_layout(stats["layout"], FIELDS)
        df[fields].rename(columns=headers).to_csv(out_csv, index=False)
        print(f"\n{len(df)} rows -> {out_csv}")
        print("header: " + ", ".join(headers[f] for f in fields))
        print(f"divisions: {df['division'].nunique()} | "
              f"dates: {list(df['date'].unique())}")

    # The bouts of a draw sheet are a different shape from its standings — one
    # row per fight, not per boxer — so they get their own file rather than a
    # column that is null for half the rows.
    if all_bouts:
        bouts_csv = Path(out_csv).with_name(Path(out_csv).stem + "_bouts.csv")
        bf = build_bouts(all_bouts)
        fields, headers = table_layout(stats["layout"], BOUT_FIELDS)
        bf[fields].rename(columns=headers).to_csv(bouts_csv, index=False)
        print(f"\n{len(bf)} bouts -> {bouts_csv}")
        print("header: " + ", ".join(headers[f] for f in fields))
        print(f"rounds: {[r for r in bf['round'].dropna().unique()]}")

    if stats["flagged"]: print(f"\nPAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  print(f"pages that errored: {stats['failed']}")
