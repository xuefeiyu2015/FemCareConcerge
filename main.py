"""FemCare Concierge — main execution entry point.

Ties together all four Kaggle Capstone criteria:

  * Multi-Agent System (#1): a Router agent that delegates to a Cycle Expert or a
    Safety Guard agent (Google ADK, LLM delegation via `sub_agents`).
  * Agent Skills (#2): the Cycle Expert calls `calculate_cycle_phase` /
    `get_fertile_window` from skills.py as tools.
  * Local MCP Server (#3): the Cycle Expert fetches history through mcp_server.py
    over the Model Context Protocol (ADK `McpToolset`, stdio transport).
  * Security (#4): PII redaction (before_model) + medical disclaimer (after_model)
    guardrails from security.py.

Two run paths:
  * LIVE  — when GOOGLE_API_KEY is set: real Gemini agents via the ADK Runner.
  * OFFLINE — no key/network: deterministic keyword routing that calls the same
    skills, the same MCP server (via a real MCP client), and the same security
    functions. This keeps the demo reproducible for grading.

Usage:
    python main.py            # interactive chat
    python main.py --demo     # scripted demo of both agents (no input needed)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import warnings

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from config import PROJECT_ROOT, load_config
from security import apply_medical_disclaimer, contains_medical_keywords, redact_pii
from skills import calculate_cycle_phase, get_fertile_window

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("femcare.main")

# Keep the terminal demo clean: silence library warnings and ADK's own error
# tracebacks (we surface friendly messages ourselves in handle_live).
warnings.filterwarnings("ignore")
for _noisy in ("google_adk", "google.adk", "google_genai", "google.genai", "mcp"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

load_dotenv()  # pull GOOGLE_API_KEY from .env if present
CONFIG = load_config()
DISCLAIMER = CONFIG["security"]["disclaimer"]
MCP_SERVER_PATH = str((PROJECT_ROOT / "mcp_server.py").resolve())

console = Console()

# Per-agent display colours (Vibe-coding terminal UI).
AGENT_STYLE = {
    "Router": "bold cyan",
    "Cycle Expert": "bold green",
    "Safety Guard": "bold magenta",
    "System": "dim white",
}

# Keywords that route a message to the Safety Guard (abnormal-symptom handling).
SAFETY_TRIGGERS = (
    "pain", "delay", "delayed", "late", "bleeding", "blood", "pregnant",
    "pregnancy", "cramp", "worried", "abnormal", "hurt", "spotting",
)
# Keywords indicating a fertility question (vs. a general phase question).
FERTILITY_TRIGGERS = ("fertile", "ovulat", "conceive", "conception", "trying", "baby")


# --------------------------------------------------------------------------- #
# Terminal UI helpers
# --------------------------------------------------------------------------- #
def banner() -> None:
    """Print the app banner."""
    console.print(
        Panel(
            Text("🌸  FemCare Concierge  —  Privacy-First Period Agent", justify="center"),
            style="bold white on purple4",
        )
    )


def show_routing(agent_name: str, redacted_input: str) -> None:
    """Show which agent handled the turn and the PII-redacted input."""
    console.print(
        f"[{AGENT_STYLE['Router']}]Router[/] → delegating to "
        f"[{AGENT_STYLE.get(agent_name, 'white')}]{agent_name}[/]"
    )
    console.print(f"[dim](redacted for LLM: “{redacted_input}”)[/dim]")


def show_response(agent_name: str, text: str) -> None:
    """Render an agent's answer; split any medical disclaimer into its own panel."""
    body, disclaimer = text, None
    if DISCLAIMER and DISCLAIMER in text:
        body, disclaimer = text.split(DISCLAIMER, 1)[0].rstrip(), DISCLAIMER

    console.print(
        Panel(body or "(no content)", title=f"[{AGENT_STYLE.get(agent_name, 'white')}]{agent_name}[/]",
              border_style=AGENT_STYLE.get(agent_name, "white").split()[-1])
    )
    if disclaimer:
        console.print(Panel(disclaimer, title="[bold yellow]⚕️ Medical Disclaimer[/]",
                            border_style="yellow"))


# --------------------------------------------------------------------------- #
# MCP client (offline path) — genuinely exercises mcp_server.py over stdio
# --------------------------------------------------------------------------- #
async def mcp_fetch(tool_name: str) -> dict:
    """Call a tool on the local MCP server via a real stdio MCP client session.

    Args:
        tool_name: The MCP tool to invoke (e.g. "get_last_period").

    Returns:
        The tool's dict result, or an error dict on failure (never raises).
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=sys.executable, args=[MCP_SERVER_PATH])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, {})
                if getattr(result, "structuredContent", None):
                    # FastMCP wraps dict returns as {"result": {...}} or the dict itself.
                    sc = result.structuredContent
                    return sc.get("result", sc) if isinstance(sc, dict) else sc
                if result.content:
                    return json.loads(result.content[0].text)
    except Exception as exc:  # noqa: BLE001 - guardrail: MCP must not crash the app
        logger.error("[main] MCP fetch '%s' failed: %s", tool_name, exc)
    return {"status": "error", "message": "MCP unavailable"}


# --------------------------------------------------------------------------- #
# OFFLINE path — deterministic 3-agent simulation
# --------------------------------------------------------------------------- #
def route_offline(user_text: str) -> str:
    """Router logic: pick the specialist agent for a message."""
    lowered = user_text.lower()
    if any(kw in lowered for kw in SAFETY_TRIGGERS):
        return "Safety Guard"
    return "Cycle Expert"


async def cycle_expert_offline(user_text: str) -> str:
    """Cycle Expert: use MCP history + skills to answer prediction questions."""
    last = await mcp_fetch("get_last_period")
    # Cold start: no local history — ask the user to supply their details.
    if isinstance(last, dict) and last.get("status") == "empty":
        return (
            "I don't have any saved cycle history for you yet. To predict your cycle, could "
            "you tell me the start date of your last period (YYYY-MM-DD) and your average "
            "cycle length in days?"
        )
    if not isinstance(last, dict) or last.get("status") != "success":
        return "I couldn't access your cycle history right now. Please try again."

    date, length = last["last_period_date"], last["cycle_length"]
    lowered = user_text.lower()

    if any(kw in lowered for kw in FERTILITY_TRIGGERS):
        window = get_fertile_window(date, length)
        if window.get("status") != "success":
            return "I couldn't compute your fertile window from the available data."
        return (
            f"Based on your last period ({date}) and a {length}-day cycle:\n"
            f"• Predicted ovulation: {window['ovulation_date']}\n"
            f"• Fertile window: {window['fertile_window_start']} → {window['fertile_window_end']}\n"
            f"• Next period expected: {window['next_period_date']}"
        )

    phase = calculate_cycle_phase(date, length)
    window = get_fertile_window(date, length)
    return (
        f"Using your records (last period {date}, {length}-day cycle):\n"
        f"• You are currently in your {phase}\n"
        f"• Next period expected around {window.get('next_period_date', 'N/A')}"
    )


def safety_guard_offline(user_text: str) -> str:
    """Safety Guard: empathetic response; disclaimer force-appended."""
    reply = (
        "I hear you, and I'm sorry you're dealing with this. Changes like a delayed "
        "period, unusual bleeding, or pain can have many causes — from stress and "
        "hormonal shifts to conditions that deserve a clinician's eye. Track your "
        "symptoms (timing, intensity, duration), rest, and stay hydrated."
    )
    # Force the disclaimer: the trigger keyword was in the user's prompt.
    return apply_medical_disclaimer(reply, force=True)


async def handle_offline(user_text: str) -> None:
    """Run one turn through the offline multi-agent pipeline."""
    redacted = redact_pii(user_text)              # Security: PII redaction (pre-LLM)
    agent = route_offline(redacted)               # Multi-agent: routing decision
    show_routing(agent, redacted)

    if agent == "Cycle Expert":
        answer = await cycle_expert_offline(redacted)
        # If the response itself surfaces risk keywords, still disclaim.
        answer = apply_medical_disclaimer(answer)
    else:
        answer = safety_guard_offline(redacted)
    show_response(agent, answer)


# --------------------------------------------------------------------------- #
# LIVE path — Google ADK multi-agent system
# --------------------------------------------------------------------------- #
def build_root_agent():
    """Construct the ADK Router → (Cycle Expert | Safety Guard) agent tree."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from google.genai.types import HttpRetryOptions
    from mcp import StdioServerParameters

    from security import disclaimer_callback, pii_redactor_callback

    # Retry-configured model so transient Gemini failures self-heal with
    # exponential backoff: 5xx overloads (503 "high demand", etc.) and 429
    # free-tier rate limits (~5 req/min). Shared by all three agents, so this
    # is the ONE place that protects BOTH surfaces — the CLI and the web
    # runtime (app.py / adk web), which builds from this same function and has
    # no other 429 handling. The 429 backoff ceiling (attempts=6, max_delay=60)
    # is sized to outlast a per-minute quota window (~63s cumulative); if it's
    # still exhausted afterwards, the CLI's handle_live() shows a friendly
    # fallback message.
    model = Gemini(
        model=CONFIG["model"]["name"],
        retry_options=HttpRetryOptions(
            attempts=6,
            initial_delay=1.0,
            max_delay=60.0,
            exp_base=2.0,
            http_status_codes=[429, 500, 502, 503, 504],
        ),
    )

    # MCP toolset: ADK launches mcp_server.py as a subprocess and exposes its tools.
    mcp_tools = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command=sys.executable, args=[MCP_SERVER_PATH]),
        ),
    )

    cycle_expert = Agent(
        name="cycle_expert",
        model=model,
        description="Predicts periods, cycle phase, and fertile windows from cycle data.",
        instruction=(
            "You are a menstrual-cycle expert. When you need the user's history, call the "
            "MCP tools (get_last_period / get_cycle_history). Use calculate_cycle_phase and "
            "get_fertile_window to compute answers. Be concise, warm, and factual.\n"
            "SAVING DATA: You can also LOG a period for the user. When they say things like "
            "'record my period for today' or 'log my period starting <date>', call "
            "add_period_record(start_date=YYYY-MM-DD, duration=<days, default 5>). If they don't "
            "give a date, ask for it (or confirm 'today'). After a successful save, warmly "
            "confirm what you recorded. If the tool result includes a 'note' field, gently "
            "share that note with the user too. Only write when the user clearly asks to "
            "log/record.\n"
            "COLD START: If a tool returns {'status': 'empty'}, or a calculation skill returns "
            "an {'error': 'InvalidInput'} payload, do NOT crash, retry, or guess. Stay in your "
            "empathetic concierge persona, explain that no local cycle data is available, and "
            "politely ask the user to provide their last period start date (YYYY-MM-DD) and "
            "their average cycle length in days."
        ),
        tools=[calculate_cycle_phase, get_fertile_window, mcp_tools],
        after_model_callback=disclaimer_callback,  # Security guardrail on output
    )

    safety_guard = Agent(
        name="safety_guard",
        model=model,
        description="Handles abnormal symptoms (pain, delay, bleeding, pregnancy) with empathy.",
        instruction=(
            "You are an empathetic reproductive-health safety guide. The user reports abnormal "
            "or worrying symptoms. Respond with warmth, suggest sensible self-care and symptom "
            "tracking, and never give a diagnosis."
        ),
        after_model_callback=disclaimer_callback,  # Security guardrail on output
    )

    router = Agent(
        name="router",
        model=model,
        description="Front door that routes the user to the right specialist.",
        instruction=(
            "You are the FemCare router. Read the user's message and delegate:\n"
            "• abnormal symptoms (pain, delayed/late period, unusual bleeding, pregnancy worry) "
            "→ transfer to safety_guard.\n"
            "• predictions about cycle phase, next period, ovulation, or fertile window "
            "→ transfer to cycle_expert.\n"
            "Do not answer directly; delegate."
        ),
        sub_agents=[cycle_expert, safety_guard],
        before_model_callback=pii_redactor_callback,  # Security guardrail on input
        after_model_callback=disclaimer_callback,
    )
    return router


def _is_rate_limit(exc: Exception) -> bool:
    """True if the exception is a Gemini quota / rate-limit (429) error."""
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def _is_overloaded(exc: Exception) -> bool:
    """True if Gemini returned a transient overload (503 / UNAVAILABLE) error."""
    msg = str(exc)
    return "503" in msg or "UNAVAILABLE" in msg


async def handle_live(runner, user_id: str, session_id: str, user_text: str) -> None:
    """Run one turn through the ADK Runner.

    Transient 429/5xx retries are handled at the model layer (see build_root_agent's
    HttpRetryOptions), so by the time an exception reaches here the retries are
    already exhausted — we only classify it and show a friendly final message.
    """
    from google.genai import types as genai_types

    console.print(f"[dim](redacted for LLM: “{redact_pii(user_text)}”)[/dim]")
    message = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=user_text)])

    final, author = "", "Cycle Expert"
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final = event.content.parts[0].text or ""
                author = {"cycle_expert": "Cycle Expert", "safety_guard": "Safety Guard"}.get(
                    event.author, "Cycle Expert"
                )
        show_response(author, final or "(no response)")
    except Exception as exc:  # noqa: BLE001
        if _is_rate_limit(exc):
            show_response(
                "System",
                "⏳ Gemini free-tier quota still exhausted after auto-retry. Wait a minute and "
                "try again, or raise your quota at https://ai.dev/rate-limit.",
            )
        elif _is_overloaded(exc):
            show_response(
                "System",
                "🌐 Gemini is temporarily overloaded (503). Retries were exhausted — "
                "please try again in a moment.",
            )
        else:
            logger.error("[main] Live run failed: %s", exc)
            show_response(author, "The live agent hit an error; please check your API key / network.")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def has_api_key() -> bool:
    """True if a Gemini API key is configured (enables the LIVE path)."""
    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))


DEMO_QUERIES = [
    "Hi, I'm Priya Sharma from Bangalore — what phase of my cycle am I in?",
    "When is my fertile window this month?",
    "My period is 6 days late and I have bad pelvic pain. Should I be worried?",
]


async def run(demo: bool) -> None:
    """Main async loop for either the live or offline path."""
    banner()
    live = has_api_key()
    mode = "LIVE (Gemini via ADK)" if live else "OFFLINE (deterministic fallback)"
    console.print(f"[{AGENT_STYLE['System']}]Mode: {mode}[/]\n")

    runner = user_id = session_id = None
    if live:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        root = build_root_agent()
        session_service = InMemorySessionService()
        user_id, session_id = "demo_user", "demo_session"
        await session_service.create_session(app_name="femcare", user_id=user_id, session_id=session_id)
        runner = Runner(agent=root, app_name="femcare", session_service=session_service)

    async def dispatch(text: str) -> None:
        if live:
            await handle_live(runner, user_id, session_id, text)
        else:
            await handle_offline(text)

    if demo:
        for q in DEMO_QUERIES:
            console.rule(f"[bold]User[/]: {q}")
            await dispatch(q)
            console.print()
        return

    console.print("[dim]Type your question (or 'quit' to exit).[/dim]\n")
    while True:
        try:
            user_text = console.input("[bold white]You[/] › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit", "q"}:
            break
        await dispatch(user_text)
        console.print()
    console.print(f"[{AGENT_STYLE['System']}]Take care. 🌸[/]")


def main() -> None:
    """Sync entry point."""
    demo = "--demo" in sys.argv
    try:
        asyncio.run(run(demo))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
