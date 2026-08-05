# Boxing draw-sheet OCR

Reads a tournament PDF page by page with a vision model and writes two CSVs — one
row per boxer (standings) and one row per bout — plus an audit file listing every
page whose numbers still did not add up.

```bash
export OPENAI_API_KEY=sk-...
python3 script.py [-v|-q] [--pages 3,7,12-15] <input.pdf> [output.csv]
```

Output lands in `output/`:

| File | Contents |
|---|---|
| `<name>.csv` | Standings — one row per boxer |
| `<name>_bouts.csv` | Bouts — one row per fight |
| `<name>_audit.csv` | Unresolved complaints, joinable to either file on `page` |

---

## How the files connect

```
script.py ──▶ pipeline.py ──▶ triage.py ──▶ llm.py ──▶ prompts/ ──▶ draw.py
   CLI          the hub        the gate      the API    what to ask   the maths
                     └────────────────────────────────▶ audit.py ──────┘
                                                        the checker
```

| Layer | Files | Depends on |
|---|---|---|
| 4 · Entry | `script.py` | pipeline, log |
| 3 · Orchestration | `pipeline.py` | triage, llm, audit, config, log |
| 2 · Services | `triage.py`, `llm.py`, `audit.py` | prompts, draw, config, log |
| 1 · Content | `prompts/` | draw, config |
| 0 · Leaves | `config.py`, `log.py`, `draw.py` | stdlib only |

No cycles — every arrow points down. `draw.py` sits at the bottom because two
different layers must agree on the same bracket arithmetic: `prompts/bracket.py`
teaches it to the model, `audit.py` enforces it.

Three API calls per document: the **judge** (once per non-blank page), the
**extraction** (once per kept page, plus up to `RETRY_ON_AUDIT` re-reads if the
audit complains), and the **header** call (once per document, on the first page
that returned data).

---

## Function reference

| File | Symbol | What it does | Go here when… |
|---|---|---|---|
| **[script.py](script.py)** | `USAGE:18` | Usage string | — |
| | `parse_pages(spec):21` | `"3,7,12-15"` → `[3,7,12,13,14,15]`, sorted, deduped | `--pages` rejects your input |
| | `main(argv):42` | Strip `-v/-q`, strip `--pages`, check PDF exists, mkdir `output/`, derive `out_csv`, call `run()` | Wrong output path; flags ignored; "no such file" |
| **[pipeline.py](pipeline.py)** | `Read:21` | NamedTuple `(d, rows, bouts, warns)` + `.empty` | — |
| | `Page:34` | NamedTuple `(no, keep, why, read, error)` | — |
| | `extract_pdf():43` | Opens PDF, builds page list, runs the thread pool, merges results, stamps rows, builds `stats` | Pages missing from output; wrong page counted; run crashed mid-way |
| | `one_page(i):59` | Per-page worker: probe → decide → render → read_page. **Never raises** | A page shows "FAILED" |
| | `in_page_order():93` | `pool.map` generator; `WORKERS=1` skips the pool | Output interleaved / out of order |
| | `unpack(d):178` | Drops standings and bouts that name nobody | Rows silently disappearing |
| | `check():184` | Fans out to `audit()` + `audit_bouts()` | — |
| | `read_page():194` | **Extract → audit → retry loop.** Keeps a re-read only if `severity` drops | Retries not firing; wrong answer kept; `'other'` pages |
| | `retry_temp():245` | `min(STEP*(n-1), MAX)` → 0, 0.2, 0.4 | Re-reads return identical answers |
| | `retry_note():250` | Builds the complaint text handed back to the model; varies by attempt so the cache key changes | Retries served from cache; retry prompt wording |
| | `sample_values():278` | 3 real values per field for the header call | Header call names columns badly |
| | `clean_header():285` | snake_case; rejects >25 chars or >2 underscores as "that's a value" | A good header was rejected / a value became a header |
| | `resolve_layout():297` | Model's `[(field, header)]` → `(fields, {field:header})`; drops invented/duplicate | Column order; duplicate column names |
| | `finalize():323` | Drop empty cols, drop duplicate non-CORE cols, **fill back** unchosen cols (CORE or ≥ `FILL_BACK`) | A column is missing from the CSV, or one you didn't want appeared |
| | `filled(c):331` | Column has any non-blank value | — |
| | `ISO:374` / `clean_dates():377` | Keep valid ISO, re-parse the rest from `date_raw`, blank the rest | Dates blank or wrong in the CSV |
| | `TEXT_COLS:394` | Which columns are strings, per table | A column has the wrong dtype |
| | `build_table():402` | DataFrame → strip text, clean dates, cast `rank`/`bout_no`/`points_total`, sort | Sort order; numeric columns as text |
| | `write_csv():419` | `finalize` → rename → `to_csv`. **Both files exit here** | CSVs formatted differently from each other |
| | `write_audit():434` | `<stem>_audit.csv`: one row per unresolved complaint + failed pages | Where the complaints went |
| | `run():453` | Top-level orchestrator; prints triage + token summary; returns `(df, bf, stats)` | Overall flow; the summary block at the end |
| **[triage.py](triage.py)** | `is_blank(page):17` | No selectable text **and** no images | A real page called blank |
| | `probe(page):22` | Runs under `doc_lock`: blankness + render at `JUDGE_DPI` | Thread-safety / PyMuPDF errors |
| | `decide(blank, png):33` | Blank → drop free; `PREFILTER` off → keep all; else `llm_judge` | Good pages dropped; too many pages billed |
| **[llm.py](llm.py)** | `USAGE:21` | Token totals per call-kind, under a lock | — |
| | `_record():25` | Reads the API's own `usage` block | Token numbers look wrong |
| | `usage_summary():45` | Formats the per-kind totals table | The cost report |
| | `_session():60` | Pooled session; retries 429/5xx, **`read=0`** on purpose | 429s, 5xx, timeouts, double billing |
| | `SESSION:76` / `_chat():79` | Single POST to `/chat/completions` + record usage | Auth errors, base URL, HTTP failures |
| | `_image_message():90` | Builds the `image_url` + `text` message parts | Endpoint rejects the message shape |
| | `page_png_b64():101` | `page.get_pixmap(dpi).tobytes("png")` → b64 | Image quality vs. DPI cost |
| | `_cache_path():105` | `sha1(model ∥ instructions ∥ b64)` | Stale answers; cache never hitting |
| | `extract_page():114` | **API CALL 2.** Cache → POST with `SCHEMA` → handle `finish_reason=="length"` (retry at 2× up to ceiling) | Truncated output; `OCR_MAX_OUT`; the main extraction |
| | `llm_headers():166` | **API CALL 3**, once per doc. **Fails open → `[]`** | Columns named by field name instead of the model's |
| | `llm_judge():188` | **API CALL 1**, the page filter. **Fails open → keep** | Judge decisions; `worth_reading` |
| **[audit.py](audit.py)** | `_tokens():15` | Name → set of lowercase words | Name matching too loose/strict |
| | `named(who, *boxers):21` | Subset match, so `"SMITH"` matches `"SMITH John"` | False "winner boxed in no bout" |
| | `Warn:30` | `str` subclass carrying `.weight` | — |
| | `ARITHMETIC=5 / STRUCTURAL=3:43` | Complaint weights | Retry keeps the wrong read |
| | `severity():47` | Sum of weights — what retries compare on | — |
| | `_report():52` | Dedupe, print unless `quiet` | Duplicate warnings |
| | `audit():62` | Standings checks **per division**: perfect 1..N, bronze vs rank-3, ascending ranks, `previous_rank` copying, country-code leak, missing division | A standings complaint you don't understand |
| | `audit_bouts():108` | Bout checks: winner is a colour, winner didn't box, one-sided without Bye, stray rounds, **and the `boxers_drawn` arithmetic** | "N boxers needs N-1 bouts"; "lines per round should halve" |
| **[draw.py](draw.py)** | `frame(n):8` | Next power of two ≥ n — `1 << (n-1).bit_length()` | Bracket size wrong |
| | `counts(n):16` | `(lines=frame-1, bouts=n-1, byes=frame-n)` | The arithmetic behind every weight-5 complaint |
| | `EXAMPLES:27` / `example_table():30` | Worked examples injected into the prompt | Prompt and audit disagreeing |
| **[config.py](config.py)** | `BASE_URL/MODEL/DPI:13` | Endpoint, model, render DPI | Point at another provider |
| | `FIELDS / BOUT_FIELDS / ALL_FIELDS:20` | The two tables' column vocabulary | Add or remove a field |
| | `LLM_HEADERS / HEADER_MODEL:33` | Column-naming call on/off | Turn off model-named headers |
| | `KEEP_UNCHOSEN / FILL_BACK / CORE_FIELDS:36` | Which columns survive `finalize` | A column keeps vanishing |
| | `RETRY_ON_AUDIT / TEMP_STEP / TEMP_MAX:51` | The self-correction loop | Too many / too few retries |
| | `PREFILTER / JUDGE_MODEL / JUDGE_DPI:63` | The triage gate | Turn judging off on an all-draw-sheet PDF |
| | `KEPT_* / DROP_* / TRIAGE_FAILED:69` | Reason constants — **triage writes, pipeline matches** | The triage summary line |
| | `SHOW_TOKENS / MAX_OUT / MAX_OUT_CEILING:76` | Output limits | Truncation errors |
| | `WORKERS:85` / `HTTP_RETRIES:87` / `CACHE_DIR:91` | Concurrency, HTTP retries, disk cache | Set `WORKERS=1` to debug a page; `OCR_CACHE=""` to force fresh |
| | `api_key():94` | Reads `OPENAI_API_KEY` **at call time** | "OPENAI_API_KEY is not set" |
| **[log.py](log.py)** | `_Stdout:20` | Re-reads `sys.stdout` per emit | Output lost in a notebook or `> run.log` |
| | `_Router:39` | Thread-local buffer, else straight to console | — |
| | `setup(verbosity):50` | `-1` warnings / `0` info / `1` debug | `-v` / `-q` not taking effect |
| | `collected(active):58` | Capture this thread's logs | Interleaved parallel output |
| | `replay(buf):74` | Print a captured buffer in page order | — |
| **[prompts/\_\_init\_\_.py](prompts/__init__.py)** | `PROMPT:28` | `PAGE_STEPS + STANDINGS_STEPS + BRACKET_STEPS` | The step-number registry — read this first |
| **[prompts/page.py](prompts/page.py)** | `PAGE_STEPS:12` | Steps 1–2: page type, event / division / date | Wrong `page_type`; missing event or date |
| **[prompts/standings.py](prompts/standings.py)** | `STANDINGS_STEPS:13` | Steps 3–4: where each boxer **finished** | Ranks, medals, names, points wrong |
| **[prompts/bracket.py](prompts/bracket.py)** | `BRACKET_STEPS:21` | Step 5: who boxed **whom**; teaches `draw.example_table()` | Bouts missed, byes missed |
| **[prompts/judge.py](prompts/judge.py)** | `JUDGE_PROMPT:14` | The one question the cheap model answers | Judge too strict or too lax |
| **[prompts/schema.py](prompts/schema.py)** | `SCHEMA:12` | Strict JSON schema — API rejects wrong shape/type/enum | Add a field; API 400 on schema |
| **[prompts/header.py](prompts/header.py)** | `HEADER_SCHEMA:12`, `HEADER_PROMPT:45`, `header_prompt(samples):116` | The column-naming contract + prompt | Bad CSV column names |
| **[test_smoke.py](test_smoke.py)** | — | End-to-end + unit checks over the whole chain | Verify a change didn't break anything |
| **[test_streaming.py](test_streaming.py)** | — | Checks pages print as they finish, in page order | Ordering / concurrency regressions |

---

## Quick triage

| Symptom | First file |
|---|---|
| Page skipped that shouldn't be | [triage.py](triage.py) → [prompts/judge.py](prompts/judge.py) |
| Data on the page but not in the CSV | [pipeline.py:178](pipeline.py#L178) `unpack` → [pipeline.py:323](pipeline.py#L323) `finalize` |
| Column missing / extra | [pipeline.py:323](pipeline.py#L323) `finalize` + [config.py:36](config.py#L36) |
| Column badly named | [prompts/header.py](prompts/header.py) → [pipeline.py:285](pipeline.py#L285) `clean_header` |
| Bouts short, "does not add up" | [audit.py:108](audit.py#L108) → [draw.py](draw.py) → [prompts/bracket.py](prompts/bracket.py) |
| Values wrong on the page | the relevant `prompts/*.py` |
| Cost too high | [config.py:63](config.py#L63) `PREFILTER`, [config.py:51](config.py#L51) `RETRY_ON_AUDIT` |
| Crash / truncation / 429 | [llm.py](llm.py) |
| Garbled or missing output text | [log.py](log.py) |

---

## Environment variables

All optional except the key.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required at call time** |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint |
| `OCR_MODEL` | `gpt-4o` | The extraction model |
| `OCR_JUDGE_MODEL` | `OCR_MODEL` | The page filter |
| `OCR_HEADER_MODEL` | `OCR_MODEL` | The column namer |
| `OCR_DPI` | `220` | Extraction render DPI |
| `OCR_WORKERS` | `4` | Pages read at once; `1` = strictly serial |
| `OCR_CACHE` | `.ocr_cache` | Disk cache dir; `""` disables |
| `OCR_MAX_OUT` | `8000` | Output token limit |
| `OCR_MAX_OUT_CEILING` | `16000` | Hard cap when retrying a truncated page |

---

## Debugging a single page

```bash
OCR_WORKERS=1 python3 script.py -v --pages 12 input.pdf
```

Serial, verbose, one page. Add `OCR_CACHE=""` to force a fresh call.
