"""Page loop, row assembly, and CSV output."""
import re

import fitz  # pip install pymupdf
import pandas as pd

from audit import audit
from config import DPI, FIELDS, LLM_HEADERS
from llm import extract_page, llm_headers, page_png_b64, usage_summary
from triage import decide


def extract_pdf(pdf_path):
    """Walk the PDF and return (rows, stats). Prints progress as it goes."""
    doc = fitz.open(pdf_path)
    all_rows, failed, dropped, skipped, flagged = [], [], [], [], []
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
        if not rows:
            print(f"p{i}: classified {d['page_type']} but returned no rows")
            continue

        if audit(i, d, rows):
            flagged.append(i)

        # A page can stack several weight classes, so division is a per-row answer.
        # The page-level one is only a fallback for the single-category sheets.
        for r in rows:
            r.update(event=d["event"], date=d["date_iso"], date_raw=d["date_raw"],
                     date_source=d["date_source"],
                     division=(r.get("division") or d["division"]),
                     page_type=d["page_type"], _page=i)
        all_rows += rows

        # First page that actually carried standings names the CSV's columns —
        # a page the filters admitted but that turned out to be prose would name
        # them badly. Same image, plus its finished rows so the model can see what
        # each field really holds. One extra call, then never asked again.
        if layout is None:
            layout = resolve_layout(
                llm_headers(png, sample_values(rows)) if LLM_HEADERS else [])
            print(f"  columns (from p{i}): " +
                  ", ".join(layout[1][f] for f in layout[0]))
        seen = list(dict.fromkeys(r["division"] for r in rows))
        print(f"p{i:>3}: {len(rows)} rows | {d['page_type']} | {' + '.join(map(str, seen))} "
              f"| ranks={[r['rank'] for r in rows]}")

    stats = {"failed": failed, "dropped": dropped, "skipped": skipped,
             "flagged": flagged, "reasons": reasons,
             "layout": layout or resolve_layout([])}
    return all_rows, stats


def sample_values(rows, per_field=3):
    """A few real values per field, for the header call to name columns from."""
    return {f: list(dict.fromkeys(
                str(r[f]) for r in rows if r.get(f) not in (None, "")))[:per_field]
            for f in FIELDS}


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
        if (header and field in FIELDS
                and field not in headers and header not in headers.values()):
            fields.append(field)
            headers[field] = header

    missing = [f for f in FIELDS if f not in headers]
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


def run(pdf_path, out_csv):
    print(f"reading {pdf_path} -> {out_csv}")
    all_rows, stats = extract_pdf(pdf_path)
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

    if not all_rows:
        print("No rows extracted.")
        return

    df = build_dataframe(all_rows)
    fields, headers = stats["layout"]
    df[fields].rename(columns=headers).to_csv(out_csv, index=False)

    print(f"\n{len(df)} rows -> {out_csv}")
    print("header: " + ", ".join(headers[f] for f in fields))
    print(f"divisions: {df['division'].nunique()} | dates: {list(df['date'].unique())}")
    if stats["flagged"]: print(f"PAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  print(f"pages that errored: {stats['failed']}")
