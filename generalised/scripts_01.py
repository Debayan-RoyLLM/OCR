import base64, json, os, requests, pandas as pd, fitz  # pip install pymupdf pandas requests

BASE_URL = "https://api.openai.com/v1"
API_KEY  = os.environ["OPENAI_API_KEY"]
MODEL    = "gpt-4o"          # see note on model choice below
PDF_PATH = "WorldJuniorChamps2022.pdf"
OUT_CSV  = "standings_2.csv"
DPI      = 220

COLS = ["event", "date", "division", "rank", "name", "name_short",
        "country", "medal", "date_raw", "_page"]

HINTS = ["draw sheet", "standings", "quarterfinal", "semifinal", "preliminaries"]
PREFILTER = True

# --- page triage ladder (cheapest first) -------------------------------------
# 1. keywords (free)  2. vector geometry (free)  3. mini vision model (cheap)
VECTOR_TRIAGE = True           # stage 2: does the page look like a bracket/flow chart?
LLM_TRIAGE    = False          # stage 3: ask a small vision model. costs money.
TRIAGE_MODEL  = "gpt-4o-mini"  # only used when LLM_TRIAGE is on
TRIAGE_DPI    = 110            # thumbnail resolution for stage 3
MIN_STROKES   = 25             # horizontal+vertical line segments implying a tree
MIN_BOXES     = 6              # or this many real rectangles

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


def looks_like_figure(page) -> bool:
    """Stage 2 — free, local. Bracket trees and flow charts are made of many
    short axis-aligned strokes and/or boxes; body text and tables are not."""
    h = v = boxes = 0
    try:
        drawings = page.get_drawings()
    except Exception:
        return False

    for d in drawings:
        for it in d["items"]:
            kind = it[0]
            if kind == "l":                                  # line segment
                p, q = it[1], it[2]
                dx, dy = abs(p.x - q.x), abs(p.y - q.y)
                if dy <= 1.5 and dx >= 25:
                    h += 1
                elif dx <= 1.5 and dy >= 12:
                    v += 1
            elif kind == "re":                               # rectangle
                r = it[1]
                if r.width >= 25 and r.height <= 2:
                    h += 1                                   # rule drawn as thin rect
                elif r.height >= 12 and r.width <= 2:
                    v += 1
                elif r.width >= 30 and r.height >= 15:
                    boxes += 1

    if h >= 5 and v >= 3 and h + v >= MIN_STROKES:
        return True                                          # line-and-box tree
    if boxes >= MIN_BOXES:
        return True                                          # boxed flow chart
    # scanned or image-only figure page: a picture and almost no selectable text
    return bool(page.get_images(full=True)) and len(page.get_text().strip()) < 400


def llm_has_figure(page) -> bool:
    """Stage 3 — one cheap low-detail vision call, bounded boolean answer.
    Fails OPEN: if the call errors, let the page through rather than drop it."""
    b64 = base64.b64encode(page.get_pixmap(dpi=TRIAGE_DPI).tobytes("png")).decode()
    payload = {
        "model": TRIAGE_MODEL,
        "temperature": 0,
        "max_tokens": 16,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
                {"type": "text", "text":
                    "Does this page contain a bracket tree, flow chart, graph, or other "
                    "line-and-box diagram? Plain prose, a title page, a plain table, or a "
                    "list of results is NOT a diagram. Reply with JSON only: "
                    '{"has_figure": true} or {"has_figure": false}'},
            ],
        }],
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(f"{BASE_URL}/chat/completions",
                          headers={"Authorization": f"Bearer {API_KEY}",
                                   "Content-Type": "application/json"},
                          json=payload, timeout=60)
        r.raise_for_status()
        return bool(json.loads(
            r.json()["choices"][0]["message"]["content"]).get("has_figure"))
    except Exception as e:
        print(f"  ! triage call failed ({e}) — passing page through")
        return True


def decide(page):
    """Returns (keep, reason). Ladder runs cheapest-first and short-circuits."""
    if not PREFILTER:
        return True, "prefilter off"

    t = page.get_text().lower()
    if not t.strip():
        return True, "no text layer"
    if any(x in t for x in HINTS):
        return True, "keyword"
    if VECTOR_TRIAGE and looks_like_figure(page):
        return True, "figure geometry"
    if LLM_TRIAGE and llm_has_figure(page):
        return True, "llm triage"
    return False, "no keyword, no figure"


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

    reasons = {}

    for i, page in enumerate(doc, start=1):
        keep, why = decide(page)
        reasons.setdefault(why, []).append(i)
        if not keep:
            skipped.append(i)
            continue
        if why != "keyword":
            print(f"p{i}: admitted by {why}")

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

    print("\ntriage: " + " | ".join(f"{k}={len(v)}" for k, v in reasons.items()))
    fig_only = reasons.get("figure geometry", []) + reasons.get("llm triage", [])
    if fig_only:
        print(f"pages the keyword filter would have missed: {fig_only}")

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
