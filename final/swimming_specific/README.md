# Swimming results OCR

Reads a meet result PDF page by page with a vision model and writes two CSVs —
one for the individual events and one for the relays — plus an audit file
listing every page whose numbers still did not add up.

Written against the output of meet-management software (Splash Meet Manager,
Hy-Tek), where a page is a stack of **event blocks**: a heading naming the event,
the record it was swum against, then the ranked finishers.

Every run starts by asking which endpoint to use — OpenAI, which needs only an
API key, or a custom OpenAI-compatible endpoint (vLLM, Ollama, LM Studio,
OpenRouter, a company gateway), which needs a URL, a key and the model's own
name. The answer lives in that process only; nothing is written to disk.

```
Which endpoint should this run use?
  1) OpenAI   — api.openai.com, API key only
  2) Custom   — any OpenAI-compatible endpoint: URL and API key
  choice [1]: 2
  base URL, ending at /v1 — e.g. http://localhost:8000/v1: http://localhost:11434/v1
  API key (hidden):
  model name [gpt-4o]: qwen3-vl:8b
  → qwen3-vl:8b at http://localhost:11434/v1/chat/completions
```

The URL ends at `/v1`; `/chat/completions` is appended per call, and a pasted
full endpoint is trimmed back rather than doubled. A custom endpoint is then
asked what it serves (`GET /v1/models`), so a wrong URL, a rejected key or a
model name the server has never heard of is a line printed here instead of a
404 after every PDF has downloaded. It is a warning, never fatal — gateways
that do not implement `/models` still run.

**The model must be able to see.** Every call sends a page image; a text-only
model returns nothing usable no matter how well it is named.

The environment variables below fill in the defaults the question offers, so
pressing Enter accepts them. Without a terminal — cron, CI, a notebook — the
question is skipped and those variables decide alone.

```bash
export OPENAI_API_KEY=sk-...

python3 script.py [options] <input.pdf>    [output.csv]      # one document
python3 script.py [options] <folder>       [output_folder]   # every PDF in it
python3 script.py [options] <links.csv>    [output_folder]   # one PDF URL per line
```

| Option | Meaning |
|---|---|
| `-v` / `-q` | Say everything / warnings only |
| `--pages 3,7,12-15` | Read only these pages; every page costs an API call |
| `-r` | A folder's subfolders too |
| `-s` | Skip a document whose CSV exists — resumes a stopped run |

Output lands in `output/`:

| File | Contents |
|---|---|
| `<name>.csv` | Individual events — one row per swimmer |
| `<name>_relays.csv` | Relay events — one row per swimmer per relay, carrying the team's rank, time and status alongside the leg |
| `<name>_audit.csv` | Unresolved complaints, joinable to either file on `page` |

Columns are settled **per document**, so each PDF in a batch keeps its own
headings. A link list is a plain text/CSV file of URLs; `#` comments and blank
lines are ignored, and fetched PDFs are kept in `downloads/` so a re-run resumes
and a flagged page's source can still be opened.

---

## How the files connect

```
                 ┌─ fetch.py ─┐  (a link list only)
                 │  the wire  │
script.py ──▶ batch.py ──▶ pipeline.py ──▶ triage.py ──▶ llm.py ──▶ prompts/
   CLI       many docs        the hub        the gate      the API   what to ask
                                   └───────────────────▶ audit.py
                                                          the checker
```

`script.py` calls `pipeline.run()` directly for a single PDF; `batch.py` is the
loop that calls it once per document for a folder or a link list.

| Layer | Files | Depends on |
|---|---|---|
| 5 · Entry | `script.py` | batch, pipeline, log |
| 4 · Many documents | `batch.py`, `fetch.py` | pipeline, llm, config, log |
| 3 · Orchestration | `pipeline.py` | triage, llm, audit, config, log |
| 2 · Services | `triage.py`, `llm.py`, `audit.py` | prompts, config, log |
| 1 · Content | `prompts/` | config |
| 0 · Leaves | `config.py`, `log.py` | stdlib only |

No cycles — every arrow points down. `audit.py` owns the one fact both it and
`prompts/results.py` lean on — **a race is ordered by time** — and exports
`seconds()`, which `pipeline.build_table` fills `time_sec` from, so the number in
the CSV and the number the audit compared ranks against cannot drift apart.

Three API calls per document: the **judge** (once per non-blank page), the
**extraction** (once per kept page, plus up to `RETRY_ON_AUDIT` re-reads if the
audit complains), and the **header** call (once per document, on the first page
that returned data).

---

## Function reference

| File | Symbol | What it does | Go here when… |
|---|---|---|---|
| **[script.py](script.py)** | `USAGE:31` | Usage string | — |
| | `parse_pages(spec):35` | `"3,7,12-15"` → `[3,7,12,13,14,15]`, sorted, deduped | `--pages` rejects your input |
| | `take_flag(argv,*names):56` | Strip every spelling of a flag out of `argv` | `-r`/`-s` ignored |
| | `main(argv):66` | Strip flags, then route: **dir** → `run_folder`, **.csv/.txt** → `run_links`, else one PDF → `run()` | Wrong output path; wrong mode chosen; "no such file" |
| **[batch.py](batch.py)** | `find_pdfs(folder,recursive):28` | Every PDF under a folder, stable order, `.PDF` included | A file in the folder was not read |
| | `_unique(pairs):39` | Output stems made unique — a clash takes its prefix | Two documents overwrote one CSV |
| | `out_paths(pdfs,out_dir):61` | `{pdf: CSV}`, clash prefixed by parent folder | Unexpected CSV name |
| | `link_out_paths(urls,out_dir):67` | `{url: CSV}`, named from the URL, clash prefixed by host | Unexpected CSV name |
| | `_rel(p,root):77` | How a PDF is labelled in the log — path below the input folder | Two banners read the same |
| | `_add(into,more):90` | Folds one document's token usage into the batch total | Batch usage looks wrong |
| | `_run_jobs(...):99` | **The shared loop**: obtain → `run()` → record; never raises | One bad document killed the run |
| | `run_folder(...):135` | Folder → jobs → `_run_jobs` | Batch over a folder |
| | `run_links(...):157` | Link list → jobs → `_run_jobs` | Batch over URLs |
| | `_summary(...):178` | Counts, rows/legs, empty, partial, flagged pages, failures, tokens | Reading the end-of-batch report |
| **[fetch.py](fetch.py)** | `MAX_BYTES:29`, `TIMEOUT:33` | 200 MB cap; `(15, 120)` connect/read | A huge or slow URL |
| | `_session():36` | GET session, retries 429/5xx, sets a User-Agent | Host answers 403 |
| | `read_links(path):57` | URLs in order, no repeats; `#`/blank skipped; URL found by `http` prefix, not column | A link was skipped or read twice |
| | `stem_of(url):97` | Readable name from the URL's last path segment, query dropped | Odd CSV name |
| | `local_name(url):107` | `<stem>_<sha1[:8]>.pdf` — collision-proof **and** deterministic, which is what makes reuse work | Re-downloading every run |
| | `_is_pdf(p):117` | Does the file start with `%PDF`? | — |
| | `download(url,into):127` | Reuse if good; else stream → `.part` → verify `%PDF` → rename | 404, login page, truncated file |
| **[pipeline.py](pipeline.py)** | `Read:21` | NamedTuple `(d, rows, legs, warns)` + `.empty` | — |
| | `Page:34` | NamedTuple `(no, keep, why, read, error)` | — |
| | `extract_pdf():43` | Opens PDF, builds page list, runs the thread pool, merges results, stamps rows, **carries the date across pages**, builds `stats` | Pages missing from output; wrong page counted; a continued event undated |
| | `carry:96` | `(date_iso, date_raw)` of the last dated block — what a block continued onto the next page inherits | An event's tail rows have the wrong date |
| | `one_page(i):59` | Per-page worker: probe → decide → render → read_page. **Never raises** | A page shows "FAILED" |
| | `in_page_order():93` | `pool.map` generator; `WORKERS=1` skips the pool | Output interleaved / out of order |
| | `HEADING:187` | The five fields a block's rows inherit from its heading | A row has the wrong event or phase |
| | `TEAM_KEYS:194` | A relay entry minus `name` — stamped onto each of that team's swimmers | A relay row missing its time or its Q |
| | `unpack(d):201` | **Splits `blocks` by event kind**: an individual block's rows go to the results list, a relay block goes whole to the relay list, its placing copied onto each swimmer. A team with no members line still yields one row | A relay leaking into the results file; a DNS team vanishing; rows silently disappearing |
| | `last_dated(d):218` | `(date_iso, date_raw)` of the last dated block on the page | The date carry picking the wrong block |
| | `check():247` | Fans out to `audit()` + `audit_relays()`, both over **blocks**, not flattened rows, and gated on the blocks rather than on unpack's output — a relay page yields no result rows at all | Audits skipped on an all-relay page |
| | `read_page():241` | **Extract → audit → retry loop.** Keeps a re-read only if `severity` drops | Retries not firing; wrong answer kept; `'other'` pages |
| | `retry_temp():292` | `min(STEP*(n-1), MAX)` → 0, 0.2, 0.4 | Re-reads return identical answers |
| | `retry_note():297` | The complaint text handed back to the model, with the four usual causes spelled out; varies by attempt so the cache key changes | Retries served from cache; retry prompt wording |
| | `sample_values():337` | 3 real values per field for the header call | Header call names columns badly |
| | `clean_header():344` | snake_case; rejects >25 chars or >2 underscores as "that's a value" | A good header was rejected / a value became a header |
| | `resolve_layout():356` | Model's `[(field, header)]` → `(fields, {field:header}, shown)`; drops invented/duplicate. `shown` = what the page it judged from actually held | Column order; duplicate column names |
| | `finalize():382` | Drop empty cols, drop duplicate non-CORE cols, **fill back** an unchosen col only if its page never `shown` it (or it is CORE) — a field the model saw and rejected stays out | A column is missing from the CSV, or one you didn't want appeared |
| | `ISO:433` / `clean_dates():436` | Keep valid ISO, re-parse the rest from `date_raw`, blank the rest | Dates blank or wrong in the CSV |
| | `TEXT_COLS:453` | Which columns are strings, per table | A column has the wrong dtype |
| | `build_table():461` | DataFrame → strip text, clean dates, cast `event_no`/`rank`/`leg` to `Int64`, **derive `time_sec` from `audit.seconds`**, sort by page/event/rank | Sort order; `time_sec` blank; numeric columns as text |
| | `write_csv():488` | `finalize` → rename → `to_csv`. **Both files exit here** | CSVs formatted differently from each other |
| | `write_audit():503` | `<stem>_audit.csv`: one row per unresolved complaint + failed pages | Where the complaints went |
| | `run():522` | Top-level orchestrator; prints triage + token summary; returns `(df, bf, stats)` | Overall flow; the summary block at the end |
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
| **[audit.py](audit.py)** | `Warn:20` | `str` subclass carrying `.weight` | — |
| | `ARITHMETIC=5 / STRUCTURAL=3:33` | Complaint weights | Retry keeps the wrong read |
| | `severity():37` | Sum of weights — what retries compare on | — |
| | `_report():42` | Dedupe, print unless `quiet` | Duplicate warnings |
| | `TIME:54` / `DNX:57` / `QUALIFIERS:60` | The time pattern; the codes that mean no ranked swim; `Q`/`R` | A valid time rejected; an unknown-status warning |
| | `seconds(t):63` | `"1:54.80"` → `114.8`. **`None` for anything that is not a `str`**, `pd.NA` included | `time_sec` blank; "is not a time" |
| | `_block_label():82` | `[Event 5 Men 4 x 100m Freestyle]` on a complaint, when the page holds more than one block | Which event a complaint is about |
| | `audit():92` | Result checks **per event block**: record line read as a row, rank vs status vs time, **ranks ordered by time**, ties equal, a tie consuming the ranks it skips, `Q`/`R` on the fastest | A results complaint you don't understand |
| | `_multiplier():217` | `4` out of `"4 x 100m Medley"`; `None` when not a relay | Relay checks not firing |
| | `audit_relays():223` | Relay checks: legs per team vs the multiplier, legs numbered 1..N, a swimmer twice, a members line with no ranked team | "3 of 4 legs"; "legs are numbered" |
| **[config.py](config.py)** | `OPENAI_URL / DPI:16` | OpenAI's address, render DPI | Point at another provider |
| | `FIELDS / RELAY_FIELDS / ALL_FIELDS:29` | The two tables' column vocabulary | Add or remove a field |
| | `LLM_HEADERS:38` | Column-naming call on/off | Turn off model-named headers |
| | `KEEP_UNCHOSEN / FILL_BACK / CORE_FIELDS:44` | Which columns survive `finalize` | A column keeps vanishing |
| | `RETRY_ON_AUDIT / TEMP_STEP / TEMP_MAX:55` | The self-correction loop | Too many / too few retries |
| | `PREFILTER / JUDGE_DPI:69` | The triage gate — **off by default**, since a result PDF is result pages front to back | Turn judging on for a mixed programme booklet |
| | `KEPT_* / DROP_* / TRIAGE_FAILED:72` | Reason constants — **triage writes, pipeline matches** | The triage summary line |
| | `SHOW_TOKENS / MAX_OUT / MAX_OUT_CEILING:79` | Output limits | Truncation errors |
| | `WORKERS:88` / `HTTP_RETRIES:90` / `CACHE_DIR:94` | Concurrency, HTTP retries, disk cache | Set `WORKERS=1` to debug a page; `OCR_CACHE=""` to force fresh |
| | `_root():112` | Trims a pasted `…/v1/chat/completions` back to `…/v1` | Calls 404ing on a custom endpoint |
| | `_PROVIDER:126` / `set_provider():133` | URL, key and model for this run — **not import-time constants** | A choice at startup not reaching the calls |
| | `base_url() / model() / judge_model() / header_model():142` | What `llm.py` asks per call | Wrong endpoint or model in a request |
| | `api_key():160` | The key, read **at call time** | "no API key — set `OPENAI_API_KEY` or answer the prompt" |
| | `_probe():192` | `GET /v1/models` on a custom endpoint — warns, never stops | A URL, key or model name that is wrong |
| | `choose_provider():228` | The startup question: OpenAI or custom | Prompt not appearing (no terminal → env decides) |
| **[log.py](log.py)** | `_Stdout:20` | Re-reads `sys.stdout` per emit | Output lost in a notebook or `> run.log` |
| | `_Router:39` | Thread-local buffer, else straight to console | — |
| | `setup(verbosity):50` | `-1` warnings / `0` info / `1` debug | `-v` / `-q` not taking effect |
| | `collected(active):58` | Capture this thread's logs | Interleaved parallel output |
| | `replay(buf):74` | Print a captured buffer in page order | — |
| **[prompts/\_\_init\_\_.py](prompts/__init__.py)** | `PROMPT:28` | `PAGE_STEPS + RESULTS_STEPS + RELAY_STEPS` | The step-number registry — read this first |
| **[prompts/page.py](prompts/page.py)** | `PAGE_STEPS:16` | Steps 1–2: page type, then each block's event / phase / date. **Step 2c keeps the record line out of the results** | Wrong `page_type`; a record holder appearing as a row; a continued block undated |
| **[prompts/results.py](prompts/results.py)** | `RESULTS_STEPS:13` | Step 3: where each swimmer **finished** — the team column labelled `YB`, ties printed once, annotation lines, `DNS`/`DSQ` vs `Q`/`R` | Ranks, teams, times or statuses wrong |
| **[prompts/relay.py](prompts/relay.py)** | `RELAY_STEPS:16` | Step 4: who swam which **leg** | Relay members missed or mis-ordered |
| **[prompts/judge.py](prompts/judge.py)** | `JUDGE_PROMPT:16` | The one question the cheap model answers | Judge too strict or too lax |
| **[prompts/schema.py](prompts/schema.py)** | `SCHEMA:73` | Strict JSON schema — API rejects wrong shape/type/enum | Add a field; API 400 on schema |
| **[prompts/header.py](prompts/header.py)** | `HEADER_SCHEMA:12`, `HEADER_PROMPT:45`, `header_prompt(samples):116` | The column-naming contract + prompt | Bad CSV column names |

---

## Quick triage

| Symptom | First file |
|---|---|
| Page skipped that shouldn't be | [triage.py](triage.py) → [prompts/judge.py](prompts/judge.py) |
| Data on the page but not in the CSV | [pipeline.py:194](pipeline.py#L194) `unpack` → [pipeline.py:382](pipeline.py#L382) `finalize` |
| Column missing / extra | [prompts/header.py](prompts/header.py) decides it; [pipeline.py:382](pipeline.py#L382) `finalize` + [config.py:44](config.py#L44) only rescue what its page could not show |
| Column badly named | [prompts/header.py](prompts/header.py) → [pipeline.py:344](pipeline.py#L344) `clean_header` |
| A ranked swimmer is faster than the one above | [audit.py:92](audit.py#L92) → [prompts/results.py](prompts/results.py) — a digit in one of the two times |
| A tie lost its second rank | [prompts/results.py](prompts/results.py) STEP 3b |
| The record holder appears as a competitor | [prompts/page.py](prompts/page.py) STEP 2c |
| A continued event has the wrong date | [pipeline.py:96](pipeline.py#L96) `carry` → [pipeline.py:218](pipeline.py#L218) `last_dated` |
| Relay members missing or in one cell | [prompts/relay.py](prompts/relay.py) → [audit.py:223](audit.py#L223) |
| A relay showing up in the individual CSV | [pipeline.py:201](pipeline.py#L201) `unpack` → `audit._multiplier` |
| Values wrong on the page | the relevant `prompts/*.py` |
| Cost too high | [config.py:69](config.py#L69) `PREFILTER`, [config.py:57](config.py#L57) `RETRY_ON_AUDIT` |
| Crash / truncation / 429 | [llm.py](llm.py) |
| Garbled or missing output text | [log.py](log.py) |

---

## Environment variables

All optional except the key.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required at call time**; the default the prompt offers |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint |
| `OCR_MODEL` | `gpt-4o` | The extraction model |
| `OCR_JUDGE_MODEL` | `OCR_MODEL` | The page filter |
| `OCR_HEADER_MODEL` | `OCR_MODEL` | The column namer |
| `OCR_DPI` | `220` | Extraction render DPI |
| `OCR_WORKERS` | `4` | Pages read at once; `1` = strictly serial |
| `OCR_CACHE` | `.ocr_cache` | Disk cache dir; `""` disables |
| `OCR_DOWNLOADS` | `downloads` | Where PDFs fetched from a link list are kept |
| `OCR_MAX_OUT` | `8000` | Output token limit |
| `OCR_MAX_OUT_CEILING` | `16000` | Hard cap when retrying a truncated page |

---

## Debugging a single page

```bash
OCR_WORKERS=1 python3 script.py -v --pages 12 input.pdf
```

Serial, verbose, one page. Add `OCR_CACHE=""` to force a fresh call.
