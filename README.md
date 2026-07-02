# 🌸 FemCare Concierge — A Privacy-First Period Agent

A terminal-based, multi-agent AI assistant for menstrual-cycle questions, built for the
**Kaggle "5-Day AI Agents Intensive" Capstone**. It predicts cycle phase and fertile
windows, handles worrying symptoms with empathy, and treats a user's health data as
private by design.

It runs in two modes automatically:

- **LIVE** — real Google **Gemini** agents via the **Google ADK** (when a `GOOGLE_API_KEY` is set).
- **OFFLINE** — a deterministic fallback that calls the same skills, the same MCP server, and
  the same security guardrails, so the demo is fully reproducible without a key or network.

---

## 🚀 Quick Start

Three commands — reproducible by any judge in under a minute:

```bash
make install   # checks python3, creates an isolated .venv, installs the pinned deps
make run       # guards GOOGLE_API_KEY (prints a friendly setup guide if missing),
               # then boots the Web Dev-UI + the local MCP server
make clean     # resets user_data.json to a pristine cold-start state (keeps .venv)
```

Then open **<http://localhost:8000/dev-ui/>** and pick the **`femcare_agent`** app.
No API key? It still runs — `python main.py` drops into a fully offline deterministic mode.

---

## How this meets the four Capstone criteria

| # | Criterion | Where it lives | What it does |
|---|-----------|----------------|--------------|
| 1 | **Multi-Agent System** | `main.py` (`build_root_agent`) | An ADK **Router** agent delegates (via `sub_agents`) to a **Cycle Expert** or a **Safety Guard**. The offline path mirrors this with keyword routing. |
| 2 | **Agent Skills (tools)** | `skills.py` | `calculate_cycle_phase` and `get_fertile_window` are registered as ADK function tools (docstrings + type hints drive tool-calling). |
| 3 | **Local MCP Server** | `mcp_server.py` | A real `mcp` SDK **stdio** server is the *only* component that reads **and writes** `user_data.json`. Tools: `get_cycle_history`, `get_last_period`, and a write-back `add_period_record` (atomic save) so the agent can actually log a period. The Cycle Expert uses these via ADK `McpToolset`, never touching the file directly. |
| 4 | **Security Features** | `security.py` | **PII Redactor** — a dynamic, profile-driven + pattern-based interceptor: name/location/contextual-age are derived at runtime from `user_data.json` (`[USER]`/`[LOCATION]`/`[AGE]`), plus universal email → `[EMAIL]` and phone → `[PHONE]` matchers; boundary-safe for Latin **and** CJK, and degrades gracefully on cold start. Runs on the `before_model` callback. **Medical Disclaimer** guardrail appends the mandated Aura Alert when *pain/delay/bleeding/pregnant* appear (`after_model` callback). |

---

## Architecture

```
                ┌──────────────┐   PII redaction (before_model)
   user input → │ Router Agent │   disclaimer (after_model)
                └──────┬───────┘
          ┌────────────┴─────────────┐
          ▼                          ▼
 ┌──────────────────┐       ┌──────────────────┐
 │  Cycle Expert    │       │  Safety Guard     │
 │  • skills.py     │       │  • empathetic     │
 │  • MCP tools ────┼──▶ mcp_server.py (stdio)  │
 └──────────────────┘       └──────────────────┘
```

---

## 🛡️ Architectural Edge: Local Sovereignty & Bi-Directional Privacy Firewall

FemCare treats privacy as a **two-way firewall** wrapped around the single point of cloud
exposure — the LLM call. Personal data is **sanitized on the way out** and **confined to the
local machine on the way back**. The user's raw identity never crosses the network, and even
at rest the on-disk record is anonymous.

```
┌──────────────────────────────── YOUR MACHINE · single tenant · no external DB ────────────────────────────────┐
│                                                                                                                │
│   User prompt                                                                                                  │
│   "I'm Priya Sharma, Bangalore, +1 415-555-2671"                                                               │
│        │                                                                                                       │
│        ▼                                                                                                       │
│   ① INBOUND REDACTOR  ──  security.py :: redact_pii()  (ADK before_model_callback)                             │
│        │  name→[USER]  city→[LOCATION]  age→[AGE]  email→[EMAIL]  phone→[PHONE]                                 │
│        │                                                                                                       │
│        │   …only opaque tokens are allowed to leave the machine…                                               │
│        ▼                                                                                                       │
│  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ network boundary ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌     │
│        ▼                                                                                                       │
│   ② CLOUD REASONING  ──  Gemini via Google ADK   (sees "[USER] from [LOCATION]", never the real values)        │
│        │                                                                                                       │
│        ▼                                                                                                       │
│  ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ network boundary ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌     │
│        ▼                                                                                                       │
│   ③ STRUCTURED OUTBOUND PARAMETERS  ──  the model returns a *typed tool call*, not prose:                      │
│        │        add_period_record(start_date="2026-07-28", duration=5)                                         │
│        ▼                                                                                                       │
│   ④ LOCAL MCP WRITE-BACK BOUNDARY  ──  mcp_server.py :: add_period_record() → _save_user_data()                │
│        │        atomic mutation:  write *.tmp  →  os.replace()  (crash-safe, never half-written)               │
│        ▼                                                                                                       │
│   user_data.json   ──  { "start_date": "2026-07-28", "end_date": "2026-08-01",                                 │
│   (anonymous,           "cycle_length": 31, "symptoms": [] }   ← pure numbers, zero identity                   │
│    on your disk)                                                                                                │
│                                                                                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### ① Inbound firewall — dynamic, data-driven redaction (`security.py`)
Redaction rules are **compiled at runtime from the active profile** in `user_data.json` (so the
security layer adapts the instant the DB changes — no hardcoded string list), then layered with
**universal pattern matchers** for anything a user types accidentally:
- profile-driven: name (+ tokens) → `[USER]`, location/city → `[LOCATION]`, contextual age → `[AGE]`
- universal: `[EMAIL]` and `[PHONE]` (phone is **digit-count-validated to 10–15 digits**, so dates
  like `2026-06-27` and phrases like `day 30` are never mistaken for phone numbers)

### 🌏 CJK boundary safety (the subtle bug most redactors ship)
Latin word boundaries (`\b`) don't exist in Chinese/Japanese/Korean text, so a naive matcher
either misses CJK names or **over-redacts** — a lone surname character like `李` would clobber
innocent words such as `行李` ("luggage") or `哪里` ("where"). Our solution:
- `\b…\b` for ASCII terms; **literal boundary-free match** for non-ASCII terms.
- **Single-character non-ASCII tokens are never turned into patterns.** We only redact multi-char
  terms (`len ≥ 2`). Result: `李明` → `[USER]`, while `行李` / `哪里` are left perfectly intact.

### ④ Single-tenant, physics-isolated storage (`mcp_server.py`)
There is **no external database and no cloud persistence.** State lives in exactly one local file,
`user_data.json`, reachable only through the MCP server running as a **local stdio subprocess** —
the sole component permitted to read *or* write it. Writes are **atomic** (`write .tmp` →
`os.replace`), so the file can never be left half-written. And what's stored is deliberately
**identity-free**: dates and cycle-length integers only. Even if the disk were seized, there is no
name, address, or contact to leak. That is data sovereignty by construction, not by policy.

---

## Setup

**Fastest path (Makefile):**

```bash
make install    # checks python3, creates .venv, installs pinned deps
make run        # verifies GOOGLE_API_KEY, then boots the Web Dev-UI (+ MCP server)
make clean      # reset user_data.json to a cold-start state (keeps .venv) for judges
make distclean  # clean + remove .venv
```

**Manual:**

```bash
pip install -r requirements.txt      # pinned, known-compatible versions
cp .env.example .env                 # (optional) add a key for the LIVE path
```

To enable the **LIVE** Gemini path, put an [AI Studio key](https://aistudio.google.com/apikey)
in `.env`:

```
GOOGLE_API_KEY=your_key_here
```

Without a key the app runs in **OFFLINE** mode automatically.

## Run

### Terminal (the original, always-available UI)

```bash
python main.py            # interactive chat
python main.py --demo     # scripted demo of both specialist agents
```

### Web UI (ADK local runtime)

Serves the **same** agent tree (Router → Cycle Expert / Safety Guard, with the MCP toolset
and the PII + disclaimer security callbacks) over a local FastAPI server with a chat Web UI.
Requires `GOOGLE_API_KEY` in `.env`.

```bash
python app.py             # our launcher (uvicorn) → http://localhost:8000
# — or the ADK-native CLI, run from the project root: —
adk web                   # → http://localhost:8000  (then pick "femcare_agent")
adk api_server            # headless REST/SSE API only (no Web UI)
```

Open <http://localhost:8000>, choose the **femcare_agent** app, and chat. The terminal app
(`main.py`) is untouched and remains the offline safety net.

Each component is also runnable standalone for inspection:

```bash
python config.py          # show resolved config
python skills.py          # exercise the cycle skills
python security.py        # exercise PII redaction + disclaimer
python mcp_server.py      # start the MCP server on stdio (Ctrl-C to stop)
```

---

## File map

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point; agent orchestration, `rich` terminal UI, live + offline paths. |
| `app.py` | Local web runtime — serves the same agent tree via ADK's FastAPI + Web UI. |
| `femcare_agent/` | Thin ADK agent package (`root_agent`) discovered by `adk web` / `app.py`. |
| `skills.py` | Cycle-phase and fertile-window skills (ADK tools). |
| `mcp_server.py` | Local MCP server exposing cycle history over stdio. |
| `security.py` | PII redaction + medical disclaimer (pure functions + ADK callbacks). |
| `config.py` / `config.yaml` | Central config (paths, model, cycle constants, guardrail strings). |
| `user_data.json` | Mock "encrypted local DB" of period history (read + written via MCP). |
| `Makefile` | DX commands: `install` / `run` / `clean` / `distclean`. |
| `requirements.txt` | Pinned dependencies. |

> ⚕️ **Note:** FemCare Concierge provides general information only and is **not** a medical
> device or a substitute for professional diagnosis.
