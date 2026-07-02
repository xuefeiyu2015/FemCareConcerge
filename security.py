"""Security Features — Kaggle Capstone criterion #4 (guardrails).

Two independent guardrails, each provided in two forms:

  1. Pure functions (`redact_pii`, `contains_medical_keywords`,
     `apply_medical_disclaimer`) — provider-agnostic, used by the offline
     fallback path and easy to reason about / demo.
  2. ADK callback adapters (`pii_redactor_callback` = before_model,
     `disclaimer_callback` = after_model) — the same logic wired directly into
     the LLM request/response lifecycle so it also protects the live Gemini path.

PII Redactor:  a Dynamic Profile-Driven + Pattern-Based interceptor. It (1) derives
               name/location/age redaction rules at runtime from the active user's
               profile in user_data.json (so it adapts when the mock DB changes),
               and (2) applies universal email/phone matchers to catch PII the user
               types accidentally — all BEFORE any text is sent to the LLM.
Medical Guardrail: if input or output mentions pain / delay / bleeding / pregnant,
               the mandated Aura Alert disclaimer is appended to the final output.
"""

from __future__ import annotations

import json
import logging
import re

from config import data_file_path, load_config

logger = logging.getLogger("femcare.security")


# --------------------------------------------------------------------------- #
# PII redaction — dynamic profile rules + universal pattern fallbacks
# --------------------------------------------------------------------------- #

# Profile field -> redaction tag. Names get extra token handling below.
FIELD_TAGS = {"name": "[USER]", "location": "[LOCATION]", "city": "[LOCATION]"}

# Universal matchers (compiled once, always active — even on cold start).
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
# Candidate phone spans; a digit-count check (below) confirms real phone numbers
# so dates like 2026-06-27 (8 digits) or "day 30" are never mistaken for phones.
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


def _has_non_ascii(term: str) -> bool:
    """True if the term contains any non-ASCII (e.g. CJK) character."""
    return any(ord(ch) > 127 for ch in term)


def _boundary_regex(term: str) -> re.Pattern:
    """Compile a boundary-safe, case-insensitive matcher for a literal term.

    Latin terms get `\\b...\\b` so "Priya" won't match inside "Priyanka". CJK and
    other non-ASCII terms have no word boundaries, so they match literally.
    """
    escaped = re.escape(term)
    pattern = escaped if _has_non_ascii(term) else rf"\b{escaped}\b"
    return re.compile(pattern, re.IGNORECASE)


def _age_patterns(age: str) -> list[tuple[re.Pattern, str]]:
    """Contextual age matchers → "[AGE]" (only near age words, never bare numbers)."""
    a = re.escape(age)
    return [
        # "age 34", "aged 34", "age: 34"
        (re.compile(rf"\baged?\s*:?\s*{a}\b", re.IGNORECASE), "[AGE]"),
        # "34 years old", "34 yrs", "34-year-old", "34 yo"
        (re.compile(rf"\b{a}\s*[-\s]?\s*(?:years?|yrs?|yr|y/o|yo)\b(?:[-\s]?old)?", re.IGNORECASE), "[AGE]"),
    ]


def _profile_patterns() -> list[tuple[re.Pattern, str]]:
    """Build (compiled_regex, tag) rules from the user's profile, fresh each call.

    Read at runtime (no caching) so the security layer adapts immediately if the
    mock DB changes. Returns [] on cold start (missing/empty/corrupt file), leaving
    the universal email/phone matchers to still run. Never raises.
    """
    try:
        with open(data_file_path(), "r", encoding="utf-8") as fh:
            profile = json.load(fh).get("profile", {}) or {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("[security] Profile unavailable for redaction (cold start ok): %s", exc)
        return []

    # Collect literal (term, tag) pairs. Skip terms shorter than 2 chars — a lone
    # non-ASCII surname (e.g. "李") matched without boundaries would over-redact.
    terms: list[tuple[str, str]] = []
    for field, tag in FIELD_TAGS.items():
        value = str(profile.get(field) or "").strip()
        if len(value) < 2:
            continue
        terms.append((value, tag))
        if field == "name":  # also redact each name token (first / last / …)
            terms.extend((tok, tag) for tok in value.split() if len(tok) >= 2)

    # Longest term first so "Priya Sharma" wins before "Priya".
    terms.sort(key=lambda t: len(t[0]), reverse=True)
    patterns = [(_boundary_regex(term), tag) for term, tag in terms]

    age = str(profile.get("age") or "").strip()
    if age.isdigit():
        patterns.extend(_age_patterns(age))
    return patterns


def _redact_phones(text: str) -> str:
    """Replace real phone numbers with "[PHONE]" (10–15 digits after stripping separators)."""
    def repl(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return "[PHONE]" if 10 <= len(digits) <= 15 else match.group(0)

    return _PHONE_CANDIDATE_RE.sub(repl, text)


def redact_pii(text: str) -> str:
    """Mask PII before text is sent to the LLM.

    Applies universal matchers first (email → "[EMAIL]", phone → "[PHONE]") then
    dynamic profile rules (name → "[USER]", location/city → "[LOCATION]",
    contextual age → "[AGE]").

    Args:
        text: Raw user (or intermediate) text.

    Returns:
        The redacted text. Returns the input unchanged if empty; on any error,
        returns the best-effort redaction so far (never raises).
    """
    if not text:
        return text
    redacted = text
    try:
        # Emails/phones first: redacting a whole email to [EMAIL] prevents a
        # profile name token (e.g. "priya" in priya.s@x.com) from biting into it.
        redacted = _EMAIL_RE.sub("[EMAIL]", redacted)   # 1. emails
        redacted = _redact_phones(redacted)              # 2. phone numbers
        for pattern, tag in _profile_patterns():         # 3. dynamic profile PII
            redacted = pattern.sub(tag, redacted)
    except re.error as exc:
        logger.error("[security] Redaction failed: %s", exc)
    return redacted


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
    cases = [
        # profile-driven name + location
        "Hi, I'm Priya Sharma from Bangalore and my period is delayed.",
        # universal fallbacks: email + phone (+ contextual age)
        "I'm aged 34, reach me at priya.s@example.com or +1 (415) 555-2671.",
        # numeric safety: a date and a cycle day must NOT be redacted
        "My last period was 2026-06-27 and I'm on day 30 of my cycle.",
        # boundary safety: 'Priya' inside 'Priyanka' must survive
        "My friend Priyanka asked about this too.",
    ]
    for s in cases:
        print("Original :", s)
        print("Redacted :", redact_pii(s))
        print("-" * 70)
    print("Keywords?:", contains_medical_keywords(cases[0]))
    print("Discl.   :", apply_medical_disclaimer("Your cycle looks irregular.", force=True))
