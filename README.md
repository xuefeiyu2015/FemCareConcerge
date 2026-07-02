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
