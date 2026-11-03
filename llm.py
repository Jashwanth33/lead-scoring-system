"""
LLM layer — NARRATIVE ONLY.

The score is NEVER produced here (see scoring.py). Gemini is used only to write
the 2-3 sentence lead_quality_assessment from the already-computed, rule-based
score + breakdown. If no key is configured or the provider fails, the caller
falls back to scoring.deterministic_assessment() so the API always answers.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

log = logging.getLogger("lead-scoring.llm")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

SYSTEM_PROMPT = (
    "You are a senior B2B sales-operations analyst. You receive a lead, its "
    "deterministic weighted score (0-100), classification, and per-parameter "
    "breakdown. Write the lead quality assessment ONLY.\n"
    "Rules:\n"
    "- Exactly 2-3 sentences, one paragraph, professional B2B tone.\n"
    "- Mention overall fit, intent level, and strategic value.\n"
    "- Never contradict or recompute the score; treat it as given fact.\n"
    "- No markdown, no bullets, no greetings, no preamble."
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def llm_configured() -> bool:
    provider = _env("LLM_PROVIDER", "gemini").lower()
    return provider == "gemini" and bool(_env("GEMINI_API_KEY"))


def generate_assessment(lead: dict, result: dict) -> tuple[str, str]:
    """
    Returns (assessment_text, source) where source is "llm" or "template".
    Deterministic fallback keeps the endpoint usable with zero configuration.
    """
    if not llm_configured():
        return "", "template"

    payload = {
        "lead": lead,
        "lead_score": result["lead_score"],
        "lead_classification": result["lead_classification"],
        "confidence_level": result["confidence_level"],
        "breakdown": [
            {k: b[k] for k in ("parameter", "weight", "awarded")}
            for b in result["_breakdown"]
        ],
        "negative_factors": result["negative_scoring_factors"],
    }

    model = _env("GEMINI_MODEL", "gemini-3.5-flash")
    url = GEMINI_URL.format(model=model)
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 400},
    }

    # Short connect timeout so a broken local IPv6 route fails fast,
    # one retry for Google's transient 503 "high demand" responses.
    timeout = httpx.Timeout(connect=5.0, read=18.0, write=10.0, pool=5.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = None
            for attempt in range(2):
                resp = client.post(
                    url,
                    headers={"x-goog-api-key": _env("GEMINI_API_KEY")},
                    json=body,
                )
                if resp.status_code == 503 and attempt == 0:
                    import time

                    time.sleep(1.2)
                    continue
                break
            resp.raise_for_status()
            data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            return text, "llm"
        log.warning("Gemini returned empty assessment")
    except Exception as exc:  # network, quota, shape — always degrade gracefully
        log.warning("LLM assessment failed, using template fallback: %s", exc)
    return "", "template"
