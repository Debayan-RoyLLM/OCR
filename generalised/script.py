import base64, json, os, requests, pandas as pd, fitz  # pip install pymupdf pandas requests

BASE_URL = "https://api.openai.com/v1"
API_KEY  = os.environ["OPENAI_API_KEY"]
MODEL    = "gpt-4o"          # see note on model choice below
PDF_PATH = "WorldJuniorChamps2022.pdf"
OUT_CSV  = "standings_1.csv"
DPI      = 220

COLS = ["event", "date", "division", "rank", "name", "name_short",
        "country", "medal", "date_raw", "_page"]

HINTS = ["official results","draw sheet", "standings", "quarterfinal", "semifinal", "preliminaries"]
PREFILTER = True

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "draw_sheet",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "is_draw_sheet": {"type": "boolean"},
                "event": {"type": ["string", "null"],
                          "description": "Tournament name, the largest heading at the top."},
                "division": {"type": ["string", "null"],
                             "description": "Weight/category line, e.g. 'Elite Women - 48 Kg (EW-48 kg)'."},
                "date_raw": {"type": ["string", "null"],
                             "description": "The 'As of' date exactly as printed."},
                "date_iso": {"type": ["string", "null"],
                             "description": "Same date as YYYY-MM-DD."},
                "standings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": ["integer", "null"],
                                     "description": "The digit printed BEFORE the period. Transcribe it; never renumber."},
                            "name_short": {"type": ["string", "null"],
                                           "description": "Text between the period and the '(' — exactly as printed."},
                            "country": {"type": ["string", "null"],
                                        "description": "The 3-letter code inside the parentheses."},
                            "medal": {"type": ["string", "null"],
                                      "description": "Gold, Silver, Bronze, or null."},
                            "name": {"type": ["string", "null"],
                                     "description": "Full name from the bracket's Name column matching this boxer. Null if no confident match."},
                        },
                        "required": ["rank", "name_short", "country", "medal", "name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["is_draw_sheet", "event", "division", "date_raw", "date_iso", "standings"],
            "additionalProperties": False,
        },
    },
}

PROMPT = """\
STEP 1 — Is this page a tournament Draw Sheet / bracket? Set is_draw_sheet.
If false: nulls everywhere and an empty standings array. Stop.

STEP 2 — Read the header: the tournament name (largest text at top), the weight
division line, and the "As of" date. Copy each EXACTLY as printed.

STEP 3 — Find the box labelled "Standings:". Extract ONLY the lines inside it.
Ignore the bracket tree, all bout scores (WP 5:0, RSC R1), every "Bye", the NOTES
and LEGEND sections, and the page footer.

Each standings line has this exact form:

    <rank> . <NAME> (<CCC>) <medal?>

Parse it field by field:
  rank       = the digit before the period. TRANSCRIBE IT AS PRINTED.
  name_short = the text between the period and the opening parenthesis.
  country    = the 3 letters inside the parentheses.
  medal      = Gold / Silver / Bronze, or null if nothing follows.

CRITICAL — ranks tie and repeat. Two bronze medallists are BOTH printed "3." and
must BOTH be rank 3. Four fifth-place boxers are ALL "5." and must ALL be rank 5.
Do NOT convert repeated ranks into a 1,2,3,4,5 sequence. If you output an
unbroken 1,2,3,4,5 you have made an error — re-read the printed digits.

CRITICAL — the 3-letter country code goes in `country` and NOWHERE ELSE. It must
never appear in name_short or name.

STEP 4 — For each boxer, look up their full name in the bracket's Team/Name column
on the left and put it in `name`. The box abbreviates surnames: "RANI M" is
"RANI MANJU"; a single letter like "N" or "K" is the full single-word surname such
as "NITU" or "KUSUM". If you cannot match one confidently, return null — do not guess.

Never invent a boxer who is not printed in the Standings box.
"""


def extract_page(b64: str) -> dict:
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 4000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                {"type": "text", "text": PROMPT},
            ],
        }],
        "response_format": SCHEMA,
    }
    r = requests.post(f"{BASE_URL}/chat/completions",
                      headers={"Authorization": f"Bearer {API_KEY}",
                               "Content-Type": "application/json"},
                      json=payload, timeout=300)
    r.raise_for_status()
    body = r.json()
    if body["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("output truncated — raise max_tokens")
    return json.loads(body["choices"][0]["message"]["content"])


def relevant(page) -> bool:
    if not PREFILTER:
        return True
    t = page.get_text().lower()
    return (not t.strip()) or any(h in t for h in HINTS)


def audit(page_no, d, rows):
    """Cheap checks that catch the exact failures seen in the earlier run."""
    warn = []
    ranks = [r["rank"] for r in rows if r["rank"] is not None]

    if len(ranks) >= 4 and ranks == list(range(1, len(ranks) + 1)):
        warn.append("ranks are a perfect 1..N sequence — ties likely flattened")
    if ranks != sorted(ranks):
        warn.append("ranks not in ascending order")

    bronze = sum(1 for r in rows if (r["medal"] or "").lower() == "bronze")
    at3 = sum(1 for r in rows if r["rank"] == 3)
    if bronze and bronze != at3:
        warn.append(f"{bronze} bronze medals but {at3} rows at rank 3")

    for r in rows:
        for f in ("name_short", "name"):
            v = (r[f] or "").strip()
            if len(v) == 3 and v.isupper() and v.isalpha() and v == (r["country"] or ""):
                warn.append(f"country code leaked into {f}: {v}")

    if not d["division"]:
        warn.append("division missing")

    for w in warn:
        print(f"  ! p{page_no}: {w}")
    return warn


def main():
    doc = fitz.open(PDF_PATH)
    all_rows, failed, skipped, flagged = [], [], [], []

    for i, page in enumerate(doc, start=1):
        if not relevant(page):
            skipped.append(i)
            continue

        b64 = base64.b64encode(page.get_pixmap(dpi=DPI).tobytes("png")).decode()
        try:
            d = extract_page(b64)
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

    if not all_rows:
        print("No standings extracted.")
        return

    df = pd.DataFrame(all_rows)
    for c in ("event", "division", "name", "name_short", "country", "medal", "date_raw"):
        df[c] = df[c].astype("string").str.strip()

    df["name"] = df["name"].fillna(df["name_short"])       # fall back to the box text
    df["rank"] = df["rank"].astype("Int64")
    df = df.sort_values(["_page", "rank"], na_position="last")

    df[COLS].to_csv(OUT_CSV, index=False)
    print(f"\n{len(df)} rows -> {OUT_CSV}")
    print(f"divisions: {df['division'].nunique()} | dates: {list(df['date'].unique())}")
    if flagged: print(f"PAGES TO REVIEW: {flagged}")
    if failed:  print(f"pages that errored: {failed}")


if __name__ == "__main__":
    main()
