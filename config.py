"""Central config loader for FemCare Concierge.

Loads ``config.yaml`` once and exposes it to every module so that no path,
model name, or guardrail string is hardcoded in application logic.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("femcare.config")

# Project root = directory containing this file. Used to resolve relative paths
# from config.yaml into absolute paths (ADK's McpToolset requires absolute paths).
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load and cache config.yaml as a dict.

    Returns:
        The parsed configuration. On failure a safe built-in default is returned
        so the pipeline never crashes.
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[config] Failed to load %s: %s", CONFIG_PATH, exc)
        # Minimal fallback keeps the app running even without config.yaml.
        return {
            "data": {"user_data_file": "user_data.json"},
            "model": {"name": "gemini-flash-latest", "temperature": 0.3, "max_output_tokens": 1024},
            "cycle": {"default_length": 28, "luteal_phase_length": 14, "fertile_window_days": 5,
                      "typical_period_length": 7, "max_period_length": 15},
            "security": {"medical_keywords": ["pain", "delay", "bleeding", "pregnant"], "disclaimer": ""},
        }


def data_file_path() -> Path:
    """Return the absolute path to the user data file."""
    rel = load_config()["data"]["user_data_file"]
    return (PROJECT_ROOT / rel).resolve()


if __name__ == "__main__":
    # Standalone check: print resolved config so it can be verified independently.
    cfg = load_config()
    print("Config loaded OK")
    print("  model:", cfg["model"]["name"])
    print("  data file:", data_file_path())
    print("  disclaimer set:", bool(cfg["security"]["disclaimer"]))
