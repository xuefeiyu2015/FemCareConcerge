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
import os
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from config import data_file_path

_DATE_FMT = "%Y-%m-%d"

# Keep the subprocess quiet: only warnings/errors reach the parent's terminal.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logger = logging.getLogger("femcare.mcp")

# The MCP server identity advertised to clients (the ADK agent).
mcp = FastMCP("femcare-local-db")

# Structured cold-start signal returned when there is no local cycle data at all
# (file missing/corrupt, or an empty period_history). The agent reads this payload
# and asks the user to provide their details, rather than crashing or guessing.
NO_DATA = {"status": "empty", "message": "No historical cycle data found for the user."}


def _load_user_data() -> dict:
    """Read the local (mock-encrypted) user data file. Never raises."""
    try:
        with open(data_file_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("[mcp] Failed to read user data: %s", exc)
        return {}


def _save_user_data(data: dict) -> bool:
    """Atomically persist user data to disk. Never raises; returns success.

    Writes to a temp file in the same directory then os.replace()s it into place,
    so a crash mid-write can never corrupt the real user_data.json.
    """
    path = data_file_path()
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        logger.error("[mcp] Failed to write user data: %s", exc)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


@mcp.tool()
def get_cycle_history() -> dict:
    """Return the user's historical menstrual cycle records.

    Provides past period start/end dates, per-cycle lengths, and logged symptoms
    so the agent can reason about trends (e.g. average cycle length, regularity).

    Returns:
        On success, a dict with 'status'='success', 'average_cycle_length',
        'average_period_length', and 'period_history' (a list of past cycles).
        If there is no local data, returns {'status': 'empty', 'message': ...}.
        PII (name/location) is NOT included — only cycle-reasoning data is exposed.
    """
    data = _load_user_data()
    history = data.get("period_history", []) if data else []
    if not data or not history:
        return NO_DATA  # cold start: no file / empty history

    profile = data.get("profile", {})
    return {
        "status": "success",
        "average_cycle_length": profile.get("average_cycle_length"),
        "average_period_length": profile.get("average_period_length"),
        "period_history": history,
    }


@mcp.tool()
def get_last_period() -> dict:
    """Return the user's most recent period start date and typical cycle length.

    Use this to seed cycle-phase or fertile-window predictions when the user does
    not state their last period date explicitly.

    Returns:
        On success, a dict with 'status'='success', 'last_period_date'
        ("YYYY-MM-DD"), and 'cycle_length' (int). If there is no local data,
        returns {'status': 'empty', 'message': ...}.
    """
    data = _load_user_data()
    history = data.get("period_history", []) if data else []
    if not history:
        return NO_DATA  # cold start: no file / empty history

    # History is stored chronologically; the last entry is the most recent cycle.
    latest = max(history, key=lambda rec: rec.get("start_date", ""))
    profile = data.get("profile", {})
    return {
        "status": "success",
        "last_period_date": latest.get("start_date"),
        "cycle_length": latest.get("cycle_length", profile.get("average_cycle_length", 28)),
    }


@mcp.tool()
def add_period_record(start_date: str, duration: int = 5) -> dict:
    """Log a new period for the user by saving it to the local database.

    Use this WRITE tool when the user asks to record or log a period (e.g. "record
    my period for today", "log my period starting 2026-07-28"). It appends the new
    cycle to the user's history and refreshes their average cycle/period stats.

    Args:
        start_date: First day of the period being logged, as "YYYY-MM-DD".
        duration: Number of days the period lasted (defaults to 5).

    Returns:
        {"status": "success", "message": "Record added successfully."} on success,
        or {"status": "error", "message": ...} if the input was invalid or the
        write failed.
    """
    try:
        start = datetime.strptime(start_date.strip(), _DATE_FMT)
    except (ValueError, AttributeError):
        return {"status": "error", "message": "Invalid start_date. Use YYYY-MM-DD."}
    if not isinstance(duration, int) or duration <= 0:
        return {"status": "error", "message": "Invalid duration. Use a positive number of days."}

    data = _load_user_data() or {}
    profile = data.setdefault("profile", {})
    history = data.setdefault("period_history", [])

    # Cycle length = gap from the most recent prior start to this one; fall back to
    # the profile average (or 28) when there is no prior record (cold start).
    prior_starts = [rec.get("start_date") for rec in history if rec.get("start_date")]
    if prior_starts:
        last_start = datetime.strptime(max(prior_starts), _DATE_FMT)
        cycle_length = (start - last_start).days
    else:
        cycle_length = int(profile.get("average_cycle_length") or 28)

    end_date = start + timedelta(days=duration - 1)
    history.append({
        "start_date": start.strftime(_DATE_FMT),
        "end_date": end_date.strftime(_DATE_FMT),
        "cycle_length": cycle_length,
        "symptoms": [],
    })

    # Recalculate stats: average cycle length ignores non-positive/unknown gaps.
    cycle_lengths = [r["cycle_length"] for r in history if isinstance(r.get("cycle_length"), int) and r["cycle_length"] > 0]
    if cycle_lengths:
        profile["average_cycle_length"] = round(sum(cycle_lengths) / len(cycle_lengths))
    durations = [
        (datetime.strptime(r["end_date"], _DATE_FMT) - datetime.strptime(r["start_date"], _DATE_FMT)).days + 1
        for r in history if r.get("start_date") and r.get("end_date")
    ]
    if durations:
        profile["average_period_length"] = round(sum(durations) / len(durations))

    if not _save_user_data(data):
        return {"status": "error", "message": "Could not save the record. Please try again."}
    return {"status": "success", "message": "Record added successfully."}


if __name__ == "__main__":
    # Runs the MCP server over stdio; blocks waiting for a client (Ctrl-C to stop).
    logger.info("Starting FemCare local MCP server (stdio)...")
    mcp.run(transport="stdio")
