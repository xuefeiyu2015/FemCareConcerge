# Implementation Log

## 2026-07-02 — Write-back MCP tool + professional Makefile

### Added
- `mcp_server.py`: `_save_user_data()` (atomic write via temp file + `os.replace`) and a new
  write tool `add_period_record(start_date, duration=5)` — appends a cycle (computing
  `end_date` and `cycle_length` from the prior record) and recalculates
  `average_cycle_length` / `average_period_length`. Returns
  `{"status": "success", "message": "Record added successfully."}` or an error payload. The MCP
  server is now the sole read **and write** boundary for the data file.
- `main.py`: Cycle Expert instruction now covers saving — on "record/log my period" it calls
  `add_period_record` and confirms; only writes when clearly asked.
- `Makefile` (TAB-indented): `install` (check python3 → `.venv` → deps), `run` (guards
  `GOOGLE_API_KEY`, prints setup guide if missing, else launches `app.py`), `clean` (wipe
  caches + reset `user_data.json` to cold start with a `.bak` backup, keeps `.venv`),
  `distclean` (clean + remove `.venv`), `help` default.
- `.gitignore`: ignore `*.bak`. `README.md`: Makefile quickstart + write-back tool notes.

### Verified
- `add_period_record("2026-07-28")` → success; history 6→7, `get_last_period` reflects it,
  averages refreshed; bad date / bad duration → error payloads (tested on a temp copy).
- `make help/clean/run` guards behave; `make install` builds `.venv` with the pinned deps;
  `.venv/bin/python` imports the agent tree (cycle_expert has 3 tools).
- Regression: MCP server registers all 3 tools; offline `main.py --demo` unchanged.

## 2026-07-02 — Dynamic, pattern-based PII redactor (no heavy NLP)

Refactored the PII section of `security.py` from a hardcoded term list into a Dynamic
Profile-Driven + Pattern-Based interceptor. `redact_pii(text)->str` stays the single entry
point, so callbacks and the offline path are unchanged.

### Changed
- `security.py`:
  - `_profile_patterns()` reads the profile **fresh each call** (no `lru_cache`, so it adapts
    when the mock DB changes) and builds boundary-safe regexes: name (+ tokens) → `[USER]`,
    location/city → `[LOCATION]`, contextual age (only near age words) → `[AGE]`.
  - Universal matchers `_EMAIL_RE` → `[EMAIL]` and `_redact_phones()` → `[PHONE]` (validated to
    10–15 digits so dates like `2026-06-27` and "day 30" are never mistaken for phones).
  - `_boundary_regex()` uses `\b…\b` for Latin, literal match for non-ASCII (CJK has no `\b`);
    single-character tokens are skipped to avoid CJK over-redaction (e.g. "李" in "行李").
  - Order fix: emails/phones are redacted **before** profile terms so a name token can't bite
    into an email (`priya.s@x.com`). Graceful cold-start: returns `[]` profile rules on
    missing/empty file, keeping email/phone active; never raises.
- `user_data.json`: added `"age": 34` so the dynamic age extraction is demonstrable.
- `README.md`: expanded the Security criterion description.

### Verified
- `python security.py`: name/location/age/email/phone all masked; `2026-06-27`, "day 30", and
  "Priyanka" (boundary) survive.
- Cold start (missing file): email/phone still masked, no traceback.
- CJK: `李明`→`[USER]`, `北京`→`[LOCATION]`; `行李`/`哪里` untouched.
- Regression: offline `main.py --demo` still shows `[USER]`/`[LOCATION]`.

## 2026-07-02 — Cold-start resilience (structured-data edge-case handling)

Made the app robust when `user_data.json` is missing, empty, or has no `period_history`.
Used structured dict payloads (no bare strings / brittle matching) so the LLM composes its
own empathetic reply.

### Changed
- `mcp_server.py`: added `NO_DATA = {"status": "empty", "message": ...}`; `get_cycle_history`
  and `get_last_period` return it when the file is missing/corrupt or history is empty.
- `skills.py`: added `_inputs_invalid(...)` guard + `INVALID_INPUT = {"error": "InvalidInput",
  "message": "Missing or invalid date/cycle length."}`. `calculate_cycle_phase` (now `-> dict | str`)
  and `get_fertile_window` return it for None/empty/placeholder/`<=0`/unparseable inputs — never raise.
- `main.py`: Cycle Expert instruction now tells the LLM that on `{'status': 'empty'}` or an
  `'InvalidInput'` payload it must stay in persona and ask the user for their last-period date +
  cycle length (not call the calculators). Offline `cycle_expert_offline` cleanly checks
  `last.get("status") == "empty"` and asks for the same details.

### Verified
- `python skills.py`: happy path unchanged; `None`, `""`+`0`, `"NO_DATA_FOUND"`, and `"not-a-date"`
  all return the `InvalidInput` payload.
- MCP cold start (empty history AND missing file) → both tools return `{"status": "empty", ...}`.
- LIVE Gemini cold start: agent asked the user for their details instead of calling calculators.
- OFFLINE cold start: Cycle Expert asked for details, no traceback; happy-path `--demo` unchanged.

## 2026-07-02 — Added ADK local web runtime (app.py) alongside the terminal UI

Exposed the agent tree over a local FastAPI server + Web UI without touching main.py.

### Added
- `femcare_agent/` (`__init__.py`, `agent.py`) — thin ADK agent package that re-exports
  `build_root_agent()` from main.py, so web and terminal share ONE agent definition
  (Router → Cycle Expert / Safety Guard, MCP toolset, and both security callbacks travel with it).
- `app.py` — launcher using `google.adk.cli.fast_api.get_fast_api_app(agents_dir=PROJECT_ROOT,
  web=True)`; runs uvicorn on 127.0.0.1:8000. `adk web` / `adk api_server` also work from root.
- `README.md` — added the Web UI run commands and file-map entries.

### Verified
- `/list-apps` → `["femcare_agent"]`; dev UI serves HTTP 200.
- End-to-end `/run_sse`: Router delegated to `cycle_expert`, which used MCP history + skills to
  return the correct fertile window over HTTP. Terminal `main.py` unchanged and still works.

## 2026-07-02 — Live Gemini verification + rate-limit resilience

Ran the LIVE path end-to-end after the user added a `GOOGLE_API_KEY`.

### Verified (LIVE Gemini via ADK)
- Cycle Expert: cycle-phase and fertile-window questions answered correctly using the MCP
  history + skills; Router delegated via LLM reasoning; PII redacted pre-LLM.
- Safety Guard: "late period + pelvic pain" produced an empathetic, non-diagnostic reply with
  the Aura Alert disclaimer appended by the `after_model_callback`.

### Fixed / improved (`main.py`)
- Added graceful 429 handling in `handle_live`: detects Gemini free-tier rate limits
  (`_is_rate_limit`), parses the suggested retry delay (`_retry_delay_seconds`), waits and
  retries once, and shows a clean message instead of a traceback.
- Silenced library warnings and set third-party loggers (google_adk/genai, mcp) to CRITICAL so
  the terminal demo stays clean.

### Note
- Free tier is 5 requests/min; a multi-agent turn uses several LLM calls, so rapid `--demo` runs
  can still hit the cap. Interactive one-at-a-time use is unaffected.

## 2026-07-02 — Initial build: FemCare Concierge (Privacy-First Period Agent)

Built the full Kaggle Capstone project from scratch. All four required criteria implemented
and the offline flow verified end-to-end.

### Added
- `requirements.txt` — pinned, mutually-compatible versions: `google-adk[mcp]==2.3.0`,
  `google-genai==2.10.0`, `mcp==1.28.1`, `rich==14.3.4`, `pydantic==2.13.4`,
  `python-dotenv==1.2.2`, `PyYAML==6.0.3`.
- `.env.example`, `.gitignore` — key configuration + secret/cache hygiene.
- `config.yaml` + `config.py` — central config loader (paths, model, cycle constants,
  guardrail keywords + exact disclaimer); resolves data path to an absolute path for MCP.
- `skills.py` — `calculate_cycle_phase`, `get_fertile_window` (ADK tool conventions).
- `mcp_server.py` — real `FastMCP` stdio server (`get_cycle_history`, `get_last_period`);
  sole reader of `user_data.json`; PII deliberately excluded from tool output.
- `security.py` — `redact_pii`, `contains_medical_keywords`, `apply_medical_disclaimer`
  plus ADK adapters `pii_redactor_callback` (before_model) / `disclaimer_callback` (after_model).
- `user_data.json` — mock profile (with PII) + 6-cycle history.
- `main.py` — Router → (Cycle Expert | Safety Guard) via ADK `sub_agents`; `McpToolset` wired
  to the local server; security callbacks; `rich` UI; deterministic OFFLINE fallback that uses
  a real MCP stdio client so the tested flow genuinely exercises the protocol.
- `README.md` — overview, criteria mapping, setup/run instructions.

### Decisions
- LIVE Gemini via ADK **plus** an OFFLINE fallback so grading is reproducible without a key.
- Real `mcp` SDK (not a mock) to strengthen the "local MCP Server" criterion.
- Skipped `pytest` files this sprint (per request); relying on standalone module self-tests
  and the `--demo` flow for verification.

### Verified
- `python config.py`, `python skills.py`, `python security.py` — standalone self-tests pass.
- `mcp_server.py` boots; both tools register and respond over stdio.
- `python main.py --demo` — Router correctly sends cycle questions to the Cycle Expert (uses
  skills + live MCP fetch) and the "late period + pain" case to the Safety Guard; PII is
  redacted pre-LLM and the medical disclaimer renders in its own panel.
- `build_root_agent()` constructs the full ADK tree (Router + 2 sub-agents, 2 function tools +
  McpToolset on the Cycle Expert, all three security callbacks attached).
