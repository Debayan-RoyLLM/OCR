"""Does the run TALK as it goes, or only when it is over?

    python3 test_streaming.py 4        # the pool: buffered per page, replayed
    python3 test_streaming.py 1        # serial: straight through

Stamps every line the pipeline prints and checks that page 1 lands early rather
than bunched at the end. It needs its own test because it is invisible in the
output — a run that prints everything at the end prints the same thing as one
that streams, and the difference only shows on a PDF long enough to wait for.
"""
import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(tempfile.mkdtemp())
os.environ["OPENAI_API_KEY"] = "test-not-used"
os.environ["OCR_CACHE"] = ""
os.environ["OCR_WORKERS"] = sys.argv[1] if len(sys.argv) > 1 else "4"

import fitz                                                   # noqa: E402

import config                                                 # noqa: E402
importlib.reload(config)                                      # pick up OCR_WORKERS
import llm, pipeline, triage                                  # noqa: E402
importlib.reload(pipeline)

PER_PAGE = 0.5          # how long a page's "network" takes
PAGES = 6

FAILS = []


def ok(cond, what):
    print(("  PASS  " if cond else "  FAIL  ") + what)
    if not cond:
        FAILS.append(what)


doc = fitz.open()
for i in range(1, PAGES + 1):
    doc.new_page().insert_text((72, 100), f"page {i} — Elite Women 50Kg")
pdf = "sample.pdf"
doc.save(pdf)
doc.close()


def answer(page_no):
    return {"page_type": "ranking_table", "event": "World Cup 2026",
            "division": "Elite Women - 50 Kg", "date_raw": "3 FEB. 2026",
            "date_iso": "2026-02-03", "date_source": "footer",
            "boxers_drawn": None, "rounds_printed": [], "bouts": [],
            "standings": [{"division": None, "rank": 1,
                           "name_short": f"BOXER {page_no}", "country": "IND",
                           "medal": None, "name": f"BOXER {page_no}",
                           "previous_rank": None, "points_total": None}]}


def slow_judge(b64):
    time.sleep(PER_PAGE)
    return True, "ranking table"


llm.llm_judge = triage.llm_judge = slow_judge
pipeline.extract_page = (lambda b64, note="", page_no=None, temperature=0:
                         answer(page_no))
pipeline.llm_headers = lambda b64, samples=None: []


class Stamped:
    """Stdout with a clock on it."""

    def __init__(self):
        self.lines = []

    def write(self, s):
        for line in s.splitlines():
            if line.strip():
                self.lines.append((time.monotonic() - T0, line))
        sys.__stdout__.write(s)

    def flush(self):
        sys.__stdout__.flush()


T0 = time.monotonic()
tap = Stamped()
sys.stdout = tap
pipeline.extract_pdf(pdf)
sys.stdout = sys.__stdout__
total = time.monotonic() - T0

print(f"\n--- WORKERS={config.WORKERS}, {PAGES} pages x {PER_PAGE}s of 'network' "
      f"(total {total:.2f}s)")
for t, line in tap.lines:
    print(f"  {t:5.2f}s  {line}")

first = next((t for t, line in tap.lines if line.lstrip().startswith("p  1:")), None)

ok(first is not None, "page 1 reported something at all")
ok(first is not None and first < total * 0.6,
   f"page 1 printed at {first:.2f}s, well before the run ended at {total:.2f}s")
ok(tap.lines and tap.lines[-1][0] < total + 0.05,
   "nothing was still queued when the run returned")

spread = max(t for t, _ in tap.lines) - min(t for t, _ in tap.lines)
ok(spread > PER_PAGE * 0.5,
   f"the output is spread over {spread:.2f}s rather than dumped in one burst")

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
