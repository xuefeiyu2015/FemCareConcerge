"""Security Features — Kaggle Capstone criterion #4 (guardrails).

Two independent guardrails, each provided in two forms:

  1. Pure functions (`redact_pii`, `contains_medical_keywords`,
     `apply_medical_disclaimer`) — provider-agnostic, used by the offline
     fallback path and easy to reason about / demo.
  2. ADK callback adapters (`pii_redactor_callback` = before_model,
     `disclaimer_callback` = after_model) — the same logic wired directly into
     the LLM request/response lifecycle so it also protects the live Gemini path.

PII Redactor:  masks real names & locations (from the user profile) to "[USER]" /
               "[LOCATION]" BEFORE any text is sent to the LLM.
Medical Guardrail: if input or output mentions pain / delay / bleeding / pregnant,
               the mandated Aura Alert disclaimer is appended to the final output.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from config import data_file_path, load_config

logger = logging.getLogger("femcare.security")


# --------------------------------------------------------------------------- #
# PII redaction
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _pii_terms() -> tuple[tuple[str, str], ...]:
    """Build (term, replacement) pairs from the user profile.

    Names (and each name token) -> "[USER]"; location -> "[LOCATION]". Cached so
    the file is read once. Returns an empty tuple on failure (logged).
    """
    pairs: list[tuple[str, str]] = []
    try:
        with open(data_file_path(), "r", encoding="utf-8") as fh:
            profile = json.load(fh).get("profile", {})
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("[security] Could not load PII terms: %s", exc)
        return tuple()

    name = (profile.get("name") or "").strip()
    if name:
        pairs.append((name, "[USER]"))                       # full name first
        pairs.extend((tok, "[USER]") for tok in name.split())  # then each token
    location = (profile.get("location") or "").strip()
    if location:
        pairs.append((location, "[LOCATION]"))

    # Longest terms first so "Priya Sharma" is matched before "Priya".
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return tuple(pairs)


def redact_pii(text: str) -> str:
    """Mask real names and locations before text is sent to the LLM.

    Args:
        text: Raw user (or intermediate) text.

    Returns:
        The text with known names replaced by "[USER]" and locations by
        "[LOCATION]". Returns the input unchanged if it is empty or on error.
    """
    if not text:
        return text
    try:
        redacted = text
        for term, replacement in _pii_terms():
            # Word-boundary, case-insensitive replacement.
            redacted = re.sub(rf"\b{re.escape(term)}\b", replacement, redacted, flags=re.IGNORECASE)
        return redacted
    except re.error as exc:
        logger.error("[security] Redaction failed: %s", exc)
        return text


# --------------------------------------------------------------------------- #
# Medical disclaimer guardrail
# --------------------------------------------------------------------------- #
def contains_medical_keywords(text: str) -> bool:
    """Return True if the text contains any configured medical-risk keyword."""
    if not text:
        return False
    lowered = text.lower()
    keywords = load_config()["security"]["medical_keywords"]
    return any(kw.lower() in lowered for kw in keywords)


def apply_medical_disclaimer(text: str, force: bool = False) -> str:
    """Append the mandated medical disclaimer when warranted.

    Args:
        text: The response text about to be shown to the user.
        force: If True, append regardless of keyword detection (used when the
            triggering keyword was in the *user's* prompt, not the response).

    Returns:
        The text with the Aura Alert disclaimer appended if triggered and not
        already present; otherwise the text unchanged.
    """
    disclaimer = load_config()["security"]["disclaimer"]
    if not disclaimer or disclaimer in (text or ""):
        return text
    if force or contains_medical_keywords(text):
        return f"{text}\n\n{disclaimer}"
    return text


# --------------------------------------------------------------------------- #
# ADK callback adapters (wire the pure functions into the LLM lifecycle)
# --------------------------------------------------------------------------- #
def pii_redactor_callback(callback_context, llm_request):
    """ADK before_model_callback: redact PII in every outgoing request part.

    Returning None lets the (now-redacted) request proceed to the model.
    """
    try:
        for content in getattr(llm_request, "contents", []) or []:
            for part in getattr(content, "parts", []) or []:
                if getattr(part, "text", None):
                    part.text = redact_pii(part.text)
    except Exception as exc:  # never break the request over a guardrail hiccup
        logger.error("[security] pii_redactor_callback failed: %s", exc)
    return None


def disclaimer_callback(callback_context, llm_response):
    """ADK after_model_callback: append the disclaimer to risky model output.

    Returns the (possibly modified) llm_response, or None to pass through.
    """
    try:
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            return None
        for part in parts:
            if getattr(part, "text", None) and contains_medical_keywords(part.text):
                part.text = apply_medical_disclaimer(part.text, force=True)
                return llm_response
    except Exception as exc:
        logger.error("[security] disclaimer_callback failed: %s", exc)
    return None


if __name__ == "__main__":
    # Standalone demo (per coding standard: each module runnable alone).
    sample = "Hi, I'm Priya Sharma from Bangalore and my period is delayed."
    print("Original :", sample)
    print("Redacted :", redact_pii(sample))
    print("Keywords?:", contains_medical_keywords(sample))
    print("Discl.   :", apply_medical_disclaimer("Your cycle looks irregular.", force=True))
