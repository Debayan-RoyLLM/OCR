"""Page loop, row assembly, and CSV output."""
import fitz  # pip install pymupdf
import pandas as pd

from audit import audit
from config import COLS, DPI
from llm import extract_page, page_png_b64
from triage import decide


def extract_pdf(pdf_path):
    """Walk the PDF and return (rows, stats). Prints progress as it goes."""
    doc = fitz.open(pdf_path)
    all_rows, failed, skipped, flagged = [], [], [], []
    reasons = {}

    for i, page in enumerate(doc, start=1):
        keep, why = decide(page)
        reasons.setdefault(why, []).append(i)
        if not keep:
            skipped.append(i)
            continue
        if why != "keyword":
            print(f"p{i}: admitted by {why}")

        try:
            d = extract_page(page_png_b64(page, DPI))
        except Exception as e:
            print(f"p{i}: FAILED — {e}")
            failed.append(i)
            continue

        if not d["is_draw_sheet"]:
            skipped.append(i)
            continue

        rows = [r for r in d["standings"] if r["name_short"] or r["name"]]
        if not rows:
            print(f"p{i}: draw sheet but standings box empty")
            continue

        if audit(i, d, rows):
            flagged.append(i)

        for r in rows:
            r.update(event=d["event"], date=d["date_iso"],
                     date_raw=d["date_raw"], division=d["division"], _page=i)
        all_rows += rows
        print(f"p{i:>3}: {len(rows)} rows | {d['division']} | ranks={[r['rank'] for r in rows]}")

    stats = {"failed": failed, "skipped": skipped,
             "flagged": flagged, "reasons": reasons}
    return all_rows, stats


def build_dataframe(all_rows):
    df = pd.DataFrame(all_rows)
    for c in ("event", "division", "name", "name_short", "country", "medal", "date_raw"):
        df[c] = df[c].astype("string").str.strip()

    df["name"] = df["name"].fillna(df["name_short"])       # fall back to the box text
    df["rank"] = df["rank"].astype("Int64")
    return df.sort_values(["_page", "rank"], na_position="last")


def run(pdf_path, out_csv):
    print(f"reading {pdf_path} -> {out_csv}")
    all_rows, stats = extract_pdf(pdf_path)
    reasons = stats["reasons"]

    print("\ntriage: " + " | ".join(f"{k}={len(v)}" for k, v in reasons.items()))
    fig_only = reasons.get("figure geometry", []) + reasons.get("llm triage", [])
    if fig_only:
        print(f"pages the keyword filter would have missed: {fig_only}")

    if not all_rows:
        print("No standings extracted.")
        return

    df = build_dataframe(all_rows)
    df[COLS].to_csv(out_csv, index=False)

    print(f"\n{len(df)} rows -> {out_csv}")
    print(f"divisions: {df['division'].nunique()} | dates: {list(df['date'].unique())}")
    if stats["flagged"]: print(f"PAGES TO REVIEW: {stats['flagged']}")
    if stats["failed"]:  print(f"pages that errored: {stats['failed']}")
