"""Page loop, row assembly, and CSV output."""
import fitz  # pip install pymupdf
import pandas as pd

from audit import audit
from config import COLS, DPI
from llm import extract_page, page_png_b64, usage_summary
from triage import decide


def extract_pdf(pdf_path):
    """Walk the PDF and return (rows, stats). Prints progress as it goes."""
    doc = fitz.open(pdf_path)
    all_rows, failed, dropped, skipped, flagged = [], [], [], [], []
    reasons = {}

    for i, page in enumerate(doc, start=1):
        keep, why = decide(page)
        reasons.setdefault(why, []).append(i)
        if not keep:
            dropped.append(i)            # never billed for extraction
            continue

        try:
            d = extract_page(page_png_b64(page, DPI))
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

        for r in rows:
            r.update(event=d["event"], date=d["date_iso"], date_raw=d["date_raw"],
                     date_source=d["date_source"], division=d["division"],
                     page_type=d["page_type"], _page=i)
        all_rows += rows
        print(f"p{i:>3}: {len(rows)} rows | {d['page_type']} | {d['division']} "
              f"| ranks={[r['rank'] for r in rows]}")

    stats = {"failed": failed, "dropped": dropped, "skipped": skipped,
             "flagged": flagged, "reasons": reasons}
    return all_rows, stats


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
    df[COLS].to_csv(out_csv, index=False)

    print(f"\n{len(df)} rows -> {out_csv}")
    print(f"divisions: {df['division'].nunique()} | dates: {list(df['date'].unique())}")
    if stats["flagged"]: print(f"PAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  print(f"pages that errored: {stats['failed']}")
