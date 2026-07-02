"""Local MCP Server — Kaggle Capstone criterion #3 (Model Context Protocol).

A real, lightweight MCP server (built on the official `mcp` SDK) that simulates
reading from an *encrypted local database*. It is the ONLY component allowed to
touch ``user_data.json`` — agents must go through this server's tools rather than
reading the file directly, which is the whole point of the MCP boundary:
sensitive cycle history stays behind a controlled, auditable interface.

Transport: stdio. main.py launches this file as a subprocess via ADK's
``McpToolset`` and calls the tools below over MCP. It is also runnable directly
(`python mcp_server.py`) for inspection.
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from config import data_file_path

# Keep the subprocess quiet: only warnings/errors reach the parent's terminal.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logger = logging.getLogger("femcare.mcp")

# The MCP server identity advertised to clients (the ADK agent).
mcp = FastMCP("femcare-local-db")


def _load_user_data() -> dict:
    """Read the local (mock-encrypted) user data file. Never raises."""
    try:
        with open(data_file_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("[mcp] Failed to read user data: %s", exc)
        return {}


@mcp.tool()
def get_cycle_history() -> dict:
    """Return the user's historical menstrual cycle records.

    Provides past period start/end dates, per-cycle lengths, and logged symptoms
    so the agent can reason about trends (e.g. average cycle length, regularity).

    Returns:
        A dict with 'status', 'average_cycle_length', 'average_period_length',
        and 'period_history' (a list of past cycles). PII (name/location) is NOT
        included — only the data needed for cycle reasoning is exposed.
    """
    data = _load_user_data()
    if not data:
        return {"status": "error", "message": "User data unavailable."}

    profile = data.get("profile", {})
    return {
        "status": "success",
        "average_cycle_length": profile.get("average_cycle_length"),
        "average_period_length": profile.get("average_period_length"),
        "period_history": data.get("period_history", []),
    }


@mcp.tool()
def get_last_period() -> dict:
    """Return the user's most recent period start date and typical cycle length.

    Use this to seed cycle-phase or fertile-window predictions when the user does
    not state their last period date explicitly.

    Returns:
        A dict with 'status', 'last_period_date' ("YYYY-MM-DD"), and
        'cycle_length' (int). On failure, 'status' is 'error' with a 'message'.
    """
    data = _load_user_data()
    history = data.get("period_history", [])
    if not history:
        return {"status": "error", "message": "No period history on record."}

    # History is stored chronologically; the last entry is the most recent cycle.
    latest = max(history, key=lambda rec: rec.get("start_date", ""))
    profile = data.get("profile", {})
    return {
        "status": "success",
        "last_period_date": latest.get("start_date"),
        "cycle_length": latest.get("cycle_length", profile.get("average_cycle_length", 28)),
    }


if __name__ == "__main__":
    # Runs the MCP server over stdio; blocks waiting for a client (Ctrl-C to stop).
    logger.info("Starting FemCare local MCP server (stdio)...")
    mcp.run(transport="stdio")
