"""Local web runtime for FemCare Concierge (ADK FastAPI + Web UI).

Exposes the SAME multi-agent tree as the terminal app (main.py) over HTTP using
Google ADK's built-in FastAPI integration — a chat Web UI plus a REST/SSE API.
The terminal experience in main.py is left completely intact; this is an
additional front door onto the identical agents.

Because the agent tree comes from `build_root_agent()` (via the femcare_agent
package), every guardrail travels with it:
  * PII redaction        — before_model_callback on the Router
  * Medical disclaimer    — after_model_callback on all agents
  * Local MCP server      — McpToolset (stdio) on the Cycle Expert

Run it with either:
    python app.py          # this launcher (uvicorn)
    adk web                # ADK's native CLI (run from the project root)

Then open http://localhost:8000 and pick the "femcare_agent" app.
Requires GOOGLE_API_KEY in .env (the web runtime always calls Gemini).
"""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv
from google.adk.cli.fast_api import get_fast_api_app

from config import PROJECT_ROOT

load_dotenv()  # make GOOGLE_API_KEY available to the web runtime

HOST = "127.0.0.1"
PORT = 8000

# get_fast_api_app scans `agents_dir` for agent packages and loads their
# `root_agent`. Our project root contains the `femcare_agent` package.
# web=True mounts the ADK developer Web UI (chat, traces, events).
app = get_fast_api_app(
    agents_dir=str(PROJECT_ROOT),
    web=True,
    host=HOST,
    port=PORT,
)

if __name__ == "__main__":
    print(f"🌸 FemCare Concierge web runtime → http://{HOST}:{PORT}  (app: femcare_agent)")
    uvicorn.run(app, host=HOST, port=PORT)
