"""Agent Skills — Kaggle Capstone criterion #2 (tool calling).

These plain Python functions are registered as ADK *tools* on the Cycle Expert
agent (see main.py). Because the LLM reads their docstrings and type hints to
decide when and how to call them, they follow ADK's tool conventions:

    * clear, action-oriented docstrings (sent verbatim to the model)
    * type hints on every parameter (no default values on tool params)
    * simple JSON-serializable return values (str / dict)
    * never raise into the agent — errors are caught, logged, and returned as data

They are also importable and runnable standalone (see __main__) so the offline
fallback path in main.py can call them directly without an LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config import load_config

logger = logging.getLogger("femcare.skills")

_DATE_FMT = "%Y-%m-%d"
# Ordered phase names for reference / documentation.
PHASES = ("Menstrual", "Follicular", "Ovulation", "Luteal")

# Sentinel/placeholder values the LLM might mistakenly forward as arguments.
_INVALID = {"", "none", "null", "no_data_found", "empty"}
# Structured error payload — the LLM reads this and composes its own empathetic
# reply rather than parroting a hardcoded sentence.
INVALID_INPUT = {"error": "InvalidInput", "message": "Missing or invalid date/cycle length."}


def _inputs_invalid(last_period_date, cycle_length) -> bool:
    """True if the date or cycle length is missing / a placeholder / non-positive.

    Guards against the LLM passing None, empty strings, or a marker like
    "NO_DATA_FOUND"/"empty" instead of real values. Never raises.
    """
    if last_period_date is None or str(last_period_date).strip().lower() in _INVALID:
        return True
    try:
        return int(cycle_length) <= 0
    except (TypeError, ValueError):
        return True


def _parse_date(date_str: str) -> datetime | None:
    """Parse a YYYY-MM-DD string, returning None on failure (logged)."""
    try:
        return datetime.strptime(date_str.strip(), _DATE_FMT)
    except (ValueError, AttributeError) as exc:
        logger.error("[skills] Invalid date %r (expected YYYY-MM-DD): %s", date_str, exc)
        return None


def calculate_cycle_phase(last_period_date: str, cycle_length: int) -> dict | str:
    """Determine which menstrual cycle phase the user is currently in.

    Use this when the user asks what phase they are in today, or how they might
    be feeling based on where they are in their cycle.

    Args:
        last_period_date: First day of the user's most recent period, as
            "YYYY-MM-DD".
        cycle_length: The user's typical cycle length in days (e.g. 28).

    Returns:
        On success, a short human-readable string naming the current phase
        (Menstrual, Follicular, Ovulation, or Luteal) with the cycle day. If the
        inputs are missing/invalid, a structured {'error': 'InvalidInput', ...}
        payload for the agent to handle.
    """
    if _inputs_invalid(last_period_date, cycle_length):
        return INVALID_INPUT

    start = _parse_date(last_period_date)
    if start is None:
        return INVALID_INPUT

    cfg = load_config()["cycle"]
    cycle_length = int(cycle_length)
    luteal = cfg["luteal_phase_length"]

    # Day within the current cycle, 1-indexed (wraps for cycles in the past).
    days_since = (datetime.now() - start).days
    if days_since < 0:
        return "Error: the last period date is in the future."
    cycle_day = (days_since % cycle_length) + 1

    ovulation_day = cycle_length - luteal  # e.g. day 14 for a 28-day cycle

    if cycle_day <= 5:
        phase = "Menstrual"
    elif cycle_day < ovulation_day:
        phase = "Follicular"
    elif ovulation_day <= cycle_day <= ovulation_day + 1:
        phase = "Ovulation"
    else:
        phase = "Luteal"

    return f"{phase} phase (cycle day {cycle_day} of {cycle_length})."


def get_fertile_window(last_period_date: str, cycle_length: int) -> dict:
    """Predict the ovulation date and the 5-day fertile window.

    Use this when the user asks about their fertile window, ovulation date, or
    the best days to conceive / avoid conception.

    Args:
        last_period_date: First day of the user's most recent period, as
            "YYYY-MM-DD".
        cycle_length: The user's typical cycle length in days (e.g. 28).

    Returns:
        On success, a dict with 'status'='success', 'ovulation_date',
        'fertile_window_start', 'fertile_window_end', and 'next_period_date'
        (all "YYYY-MM-DD"). If the inputs are missing/invalid, a structured
        {'error': 'InvalidInput', ...} payload for the agent to handle.
    """
    if _inputs_invalid(last_period_date, cycle_length):
        return INVALID_INPUT

    start = _parse_date(last_period_date)
    if start is None:
        return INVALID_INPUT

    cfg = load_config()["cycle"]
    cycle_length = int(cycle_length)
    luteal = cfg["luteal_phase_length"]
    window = cfg["fertile_window_days"]

    # Ovulation typically occurs ~`luteal` days before the next period.
    ovulation = start + timedelta(days=cycle_length - luteal)
    # Fertile window: the `window` days ending on ovulation day (sperm viability).
    fertile_start = ovulation - timedelta(days=window - 1)
    next_period = start + timedelta(days=cycle_length)

    return {
        "status": "success",
        "ovulation_date": ovulation.strftime(_DATE_FMT),
        "fertile_window_start": fertile_start.strftime(_DATE_FMT),
        "fertile_window_end": ovulation.strftime(_DATE_FMT),
        "next_period_date": next_period.strftime(_DATE_FMT),
    }


if __name__ == "__main__":
    # Standalone smoke test (per coding standard: each module runnable alone).
    demo_date = (datetime.now() - timedelta(days=10)).strftime(_DATE_FMT)
    print("Last period:", demo_date, "| cycle length: 28")
    print("Phase     ->", calculate_cycle_phase(demo_date, 28))
    print("Fertile   ->", get_fertile_window(demo_date, 28))
    # Cold-start / bad-input guards — all should return the InvalidInput payload.
    print("None date ->", calculate_cycle_phase(None, 28))
    print("Empty/0   ->", get_fertile_window("", 0))
    print("Marker    ->", calculate_cycle_phase("NO_DATA_FOUND", 28))
    print("Bad date  ->", calculate_cycle_phase("not-a-date", 28))
