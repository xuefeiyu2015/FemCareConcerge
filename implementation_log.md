# Implementation Log

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
