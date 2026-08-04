"""End-to-end smoke test with the network stubbed out.

    python3 test_smoke.py          # exits non-zero on a failure

Builds a synthetic PDF, fakes the three model calls, runs the REAL pipeline and
checks page triage, the retry loop, the header fallback, the disk cache and the
parallelism. No API key and no network needed.
"""
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(tempfile.mkdtemp())          # every artefact lands somewhere disposable
os.environ["OPENAI_API_KEY"] = "test-not-used"
os.environ["OCR_CACHE"] = ""          # cache off for the stubbed runs

import fitz                                                   # noqa: E402
import pandas as pd                                           # noqa: E402

import config, llm, pipeline, triage                          # noqa: E402
from audit import ARITHMETIC, Warn, named, severity           # noqa: E402
from draw import counts, example_table, frame                 # noqa: E402
from script import parse_pages                                # noqa: E402

FAILS = []


def ok(cond, what):
    print(("  PASS  " if cond else "  FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def section(title):
    print(f"\n--- {title}")


# ------------------------------------------------------------------- a fake PDF
def build_pdf(name, pages=6, blank=(3,)):
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        if i not in blank:
            page.insert_text((72, 100), f"page {i} — Elite Women 50Kg draw sheet")
    doc.save(name)
    doc.close()
    return name


PDF = build_pdf("sample.pdf")

# ---------------------------------------------------------------- fake the calls
CALLS = {"judge": 0, "extract": 0, "header": 0}
NOTES = []          # every retry note handed to extract_page, in order
TEMPS = []


def fake_judge(b64):
    CALLS["judge"] += 1
    return True, "draw sheet"


def page_answer(short=False):
    """A 4-boxer bracket: two semifinals and a final. `short` drops the final —
    what the audit's arithmetic is there to catch."""
    bouts = [
        {"division": None, "round": "Semifinals", "bout_no": None,
         "boxer_a": "ALPHA A", "country_a": "IND", "boxer_b": "BETA B",
         "country_b": "USA", "winner": "ALPHA A", "result": "WP 5:0"},
        {"division": None, "round": "Semifinals", "bout_no": None,
         "boxer_a": "GAMMA G", "country_a": "UZB", "boxer_b": "DELTA D",
         "country_b": "KAZ", "winner": "GAMMA G", "result": "RSC R1"},
        {"division": None, "round": "Final", "bout_no": None,
         "boxer_a": "ALPHA A", "country_a": "IND", "boxer_b": "GAMMA G",
         "country_b": "UZB", "winner": "ALPHA A", "result": "WP 4:1"},
    ]
    return {
        "page_type": "draw_sheet", "event": "World Cup 2026",
        "division": "Elite Women - 50 Kg", "date_raw": "3 FEB. 2026",
        "date_iso": "2026-02-03", "date_source": "footer",
        "boxers_drawn": 4, "rounds_printed": ["Semifinals", "Final"],
        "standings": [
            {"division": None, "rank": 1, "name_short": "ALPHA A", "country": "IND",
             "medal": "Gold", "name": "ALPHA ANNA",
             "previous_rank": None, "points_total": None},
            {"division": None, "rank": 2, "name_short": "GAMMA G", "country": "UZB",
             "medal": "Silver", "name": "GAMMA GITA",
             "previous_rank": None, "points_total": None},
            {"division": None, "rank": 3, "name_short": "BETA B", "country": "USA",
             "medal": "Bronze", "name": "BETA BINA",
             "previous_rank": None, "points_total": None},
            {"division": None, "rank": 3, "name_short": "DELTA D", "country": "KAZ",
             "medal": "Bronze", "name": "DELTA DIA",
             "previous_rank": None, "points_total": None},
        ],
        "bouts": bouts[:2] if short else bouts,
    }


SEEN_SHORT = set()


def fake_extract(b64, note="", page_no=None, temperature=0):
    """p5 is short once and fixes itself on the retry. p6 is short for good, so
    it exhausts RETRY_ON_AUDIT and lands in the audit sidecar."""
    CALLS["extract"] += 1
    if note:
        NOTES.append((page_no, note))
        TEMPS.append(temperature)
    if page_no == 6:
        return page_answer(short=True)
    if page_no == 5 and 5 not in SEEN_SHORT:
        SEEN_SHORT.add(5)
        return page_answer(short=True)
    return page_answer()


def fake_headers(b64, samples=None):
    """`winner` gets a header that is plainly a VALUE off the page; `country`
    and `division` are renamed legitimately."""
    CALLS["header"] += 1
    return [("event", "event"), ("date", "date"), ("division", "weight_class"),
            ("rank", "rank"), ("name", "boxer"), ("country", "noc"),
            ("medal", "medal"), ("round", "round"),
            ("boxer_a", "red_corner"), ("country_a", "red_noc"),
            ("boxer_b", "blue_corner"), ("country_b", "blue_noc"),
            ("winner", "alpha_anna_of_india_won_gold"),   # <- a value, not a name
            ("result", "result"), ("_page", "page")]


llm.llm_judge = triage.llm_judge = fake_judge
llm.extract_page = pipeline.extract_page = fake_extract
llm.llm_headers = pipeline.llm_headers = fake_headers

# --------------------------------------------------------------------- unit bits
section("draw.py: the arithmetic the prompt and the audit share")
ok(frame(5) == 8 and frame(16) == 16 and frame(17) == 32,
   "frame() picks the next power of two")
ok(counts(10) == (15, 9, 6), "10 boxers -> 15 lines, 9 bouts, 6 byes")
ok(example_table().splitlines()[0].endswith("15 lines = 15 bouts + 0 byes"),
   "the worked examples generate from that same arithmetic")

section("audit.Warn: carries a weight without ceasing to be a string")
w = Warn("3 bouts short", ARITHMETIC)
ok(w == "3 bouts short" and f"{w}" == "3 bouts short", "a Warn IS its text")
ok(severity([w, Warn("ranks out of order")]) == ARITHMETIC + 1,
   "severity adds the weights")
ok(severity([Warn("a"), Warn("b"), Warn("c")]) == 3, "plain complaints weigh 1")
ok(list(dict.fromkeys([w, Warn("3 bouts short", 1)])) == ["3 bouts short"],
   "dedupe still works")

section("audit.named: the winner column is not compared byte for byte")
ok(named("SMITH", "SMITH John", "JONES Ali"), "a surname matches the full name")
ok(named("john  smith", "SMITH, John", "JONES Ali"),
   "so do case, punctuation and word order")
ok(not named("BROWN Kim", "SMITH John", "JONES Ali"),
   "...but a boxer who is really absent is still caught")
ok(not named("", "SMITH John", "JONES Ali"), "an empty winner matches nobody")

section("resolve_layout: a bad header costs the NAME, not the column")
fields, headers = pipeline.resolve_layout(fake_headers(None))
ok("winner" in fields, "winner survives a header that was really a value")
ok(headers["winner"] == "winner", "...and falls back to its own field name")
ok(headers["country"] == "noc", "a legitimate rename is kept")
ok(headers["division"] == "weight_class", "so is weight_class")

section("script.parse_pages")
ok(parse_pages("3,7,12-15") == [3, 7, 12, 13, 14, 15], "ranges and singles mix")
ok(parse_pages(" 5 , 5 ,1") == [1, 5], "repeats collapse and the order is fixed")
try:
    parse_pages("a-b")
    ok(False, "a page spec that is not numbers is rejected")
except SystemExit:
    ok(True, "a page spec that is not numbers is rejected")

# ---------------------------------------------------------------- the whole run
section("full pipeline run (6 pages, 1 blank, WORKERS=%d)" % config.WORKERS)
CALLS.update(judge=0, extract=0, header=0)      # the unit checks above called it

_plain_judge = fake_judge


def slow_judge(b64):                            # 0.4s of "network" per page
    time.sleep(0.4)
    return _plain_judge(b64)


llm.llm_judge = triage.llm_judge = slow_judge

# Time the PAGE LOOP only: pandas and CSV writing are not what the pool speeds
# up, and including them buries the signal.
elapsed = 0.0
_real_extract_pdf = pipeline.extract_pdf


def timed(path, only=None):
    global elapsed
    t0 = time.monotonic()
    out = _real_extract_pdf(path, only=only)
    elapsed = time.monotonic() - t0
    return out


pipeline.extract_pdf = timed
df, bf, stats = pipeline.run(PDF, "out.csv")
pipeline.extract_pdf = _real_extract_pdf

section("what came out")
rows = pd.read_csv("out.csv")
bouts = pd.read_csv("out_bouts.csv")
print(rows.head(3).to_string())
print(bouts.head(3).to_string())

ok(list(rows["page"].unique()) == [1, 2, 4, 5, 6],
   "the blank page was dropped and the rest kept in page order")
ok(len(rows) == 20, f"5 pages x 4 boxers = 20 standings rows (got {len(rows)})")
ok("alpha_anna_of_india_won_gold" not in bouts.columns,
   "the value-shaped header was not used as a column name")
ok("winner" in bouts.columns, "the winner COLUMN is written anyway")
ok(bouts["winner"].notna().all(), "...and holds every winner")
ok(CALLS["header"] == 1, f"the header call happened once (got {CALLS['header']})")
ok(CALLS["judge"] == 5, f"the judge saw the 5 non-blank pages (got {CALLS['judge']})")
ok(sorted(bouts["page"].unique().tolist()) == [1, 2, 4, 5, 6],
   "bouts carry the page they were read from")

section("run() hands the frames back, not only the files")
ok(df is not None and len(df) == len(rows), "the standings frame is returned")
ok(bf is not None and len(bf) == len(bouts), "so is the bouts frame")
ok(stats["dropped"] == [3] and stats["failed"] == [] and not stats["stopped_early"],
   f"and the stats say what happened (dropped={stats['dropped']})")

section("the retry loop")
ok(5 not in stats["flagged"], "p5 was short once and the retry fixed it")
ok(6 in stats["flagged"], "p6 stayed short and is flagged for review")
# Per page: two pages with the same complaint SHOULD get the same note, and the
# cache key holds the page image, so they cannot collide.
ok(len(NOTES) == len(set(NOTES)),
   f"no page was asked the identical question twice ({len(NOTES)} retries sent, "
   f"{len(set(NOTES))} distinct)")
ok(len({n for p, n in NOTES if p == 6}) == config.RETRY_ON_AUDIT,
   f"p6's {config.RETRY_ON_AUDIT} retries were {config.RETRY_ON_AUDIT} different "
   f"questions (got {len({n for p, n in NOTES if p == 6})})")
ok(TEMPS[:1] == [0], "the first re-read is still deterministic")
ok(len(TEMPS) < 2 or max(TEMPS) > 0,
   "later re-reads get more freedom than the one before")

section("the audit sidecar")
audit_csv = Path("out_audit.csv")
ok(audit_csv.exists(), "an unresolved page writes out_audit.csv")
if audit_csv.exists():
    a = pd.read_csv(audit_csv)
    print(a.to_string())
    ok(set(a["page"]) == {6}, f"one row per complaint on p6 (got {sorted(set(a['page']))})")
    ok({"page", "weight", "complaint"} <= set(a.columns), "joinable on the page column")

# 5 judged pages x 0.4s = 2.0s serial; with a pool it must be well under.
if config.WORKERS > 1:
    ok(elapsed < 1.4,
       f"the pages really ran in parallel ({elapsed:.2f}s, serial would be ~2.0s)")

# ------------------------------------------------------- a page that blows up
section("a page that raises is contained, and the run still writes its CSVs")
PDF2 = build_pdf("boom.pdf", pages=3, blank=())
SEEN_SHORT.clear()
NOTES.clear()


def exploding_extract(b64, note="", page_no=None, temperature=0):
    if page_no == 2:
        raise RuntimeError()      # NOTE: no message. str(e) is "" — see below.
    return fake_extract(b64, note, page_no, temperature)


pipeline.extract_page = exploding_extract
llm.llm_judge = triage.llm_judge = fake_judge
df2, bf2, stats2 = pipeline.run(PDF2, "boom.csv")
pipeline.extract_page = fake_extract

# The regression: str(RuntimeError()) is "", so a message-less exception tested
# truthily fell through to page.read.d on a page that has no read at all.
ok(stats2["failed"] == [2], f"the page that raised is recorded (got {stats2['failed']})")
ok(df2 is not None and sorted(df2["page"].unique()) == [1, 3],
   "and the pages either side of it were still written")
ok("extraction failed" in pd.read_csv("boom_audit.csv")["complaint"].tolist(),
   "the sidecar names it too")

# ------------------------------------------------------------------ page picking
section("--pages reads only what it was asked for")
CALLS.update(judge=0, extract=0, header=0)
SEEN_SHORT.clear()
df3, bf3, stats3 = pipeline.run(PDF, "few.csv", only=[1, 4, 99])
ok(sorted(df3["page"].unique()) == [1, 4], "pages 1 and 4 only")
ok(CALLS["extract"] == 2, f"and nothing else was paid for (got {CALLS['extract']})")
ok(99 not in stats3["reasons"].get("", []), "a page past the end is ignored, not an error")

# --------------------------------------------------------------- the disk cache
section("the disk cache")
os.environ["OCR_CACHE"] = ".cache_test"
importlib.reload(config)
importlib.reload(llm)

calls = {"n": 0, "max_tokens": None}


def counted_chat(payload, timeout, label="call"):
    calls["n"] += 1
    calls["max_tokens"] = payload["max_tokens"]
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": json.dumps(page_answer())}}],
            "usage": {}}


llm._chat = counted_chat
a = llm.extract_page("PRETEND-PNG", page_no=1)
b = llm.extract_page("PRETEND-PNG", page_no=1)
ok(calls["n"] == 1, f"the second read of the same page cost no call (calls={calls['n']})")
ok(a == b, "and gave back the same answer")
llm.PROMPT = llm.PROMPT + "\nAN EDIT TO THE PROMPT\n"
llm.extract_page("PRETEND-PNG", page_no=1)
ok(calls["n"] == 2, "editing the prompt invalidated it, as it must")

section("truncated output asks again, but never past the ceiling")
truncations = {"n": 0}


def truncating_chat(payload, timeout, label="call"):
    truncations["n"] += 1
    calls["max_tokens"] = payload["max_tokens"]
    reason = "length" if truncations["n"] == 1 else "stop"
    return {"choices": [{"finish_reason": reason,
                         "message": {"content": json.dumps(page_answer())}}],
            "usage": {}}


llm._chat = truncating_chat
llm.MAX_OUT_CEILING = llm.MAX_OUT + 500
llm.extract_page("TRUNCATED-PNG", page_no=1)
ok(calls["max_tokens"] == llm.MAX_OUT + 500,
   f"the retry is clamped to the ceiling (asked for {calls['max_tokens']})")

truncations["n"] = 0
llm.MAX_OUT_CEILING = llm.MAX_OUT          # a model with no room above MAX_OUT
try:
    llm.extract_page("TRUNCATED-PNG-2", page_no=1)
    ok(False, "no room above the ceiling fails honestly instead of sending a 400")
except RuntimeError:
    ok(truncations["n"] == 1,
       "no room above the ceiling fails honestly instead of sending a 400")

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED:\n  - "
                                           + "\n  - ".join(FAILS)))
sys.exit(1 if FAILS else 0)
