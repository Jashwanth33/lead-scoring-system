"""
AI-Based Lead Scoring System — FastAPI application.

POST /api/score  -> deterministic weighted score (scoring.py)
                    + optional Gemini-written assessment (llm.py)
GET  /           -> single-page UI (static/)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import llm
import scoring

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("lead-scoring.api")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def load_dotenv(path: Path) -> None:
    """Tiny .env loader (no extra dependency). Existing env always wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(BASE_DIR / ".env")

app = FastAPI(
    title="AI-Based Lead Scoring System",
    description="Explainable, deterministic lead scoring with LLM-written narratives.",
    version="1.0.0",
)


class ScoreRequest(BaseModel):
    # Accepts either {"lead": {...}} or a flat lead object (extra fields allowed)
    lead: dict | None = None

    model_config = {"extra": "allow"}


REQUIRED_OUTPUT_KEYS = [
    "lead_classification",
    "lead_quality_assessment",
    "positive_scoring_factors",
    "negative_scoring_factors",
    "scoring_explanation",
    "confidence_level",
    "recommended_next_action",
]


def build_response(raw_lead: dict) -> dict:
    result = scoring.score_lead(raw_lead)
    assessment, source = llm.generate_assessment(result["_normalized_lead"], result)
    if source != "llm":
        assessment = scoring.deterministic_assessment(result)

    return {
        # required by the assignment (0-100 score)
        "lead_score": result["lead_score"],
        "lead_classification": result["lead_classification"],
        "lead_quality_assessment": assessment,
        "assessment_source": source,
        "positive_scoring_factors": result["positive_scoring_factors"],
        "negative_scoring_factors": result["negative_scoring_factors"],
        "scoring_explanation": result["scoring_explanation"],
        "confidence_level": result["confidence_level"],
        "recommended_next_action": result["recommended_next_action"],
        "score_breakdown": result["_breakdown"],
        "subscores": result["_subscores"],
        "weights": scoring.WEIGHTS,
        "thresholds": scoring.THRESHOLDS,
    }


@app.post("/api/score")
def score(payload: ScoreRequest | dict):
    """Score a lead. Accepts {'lead': {...}} or a flat lead object."""
    if isinstance(payload, ScoreRequest):
        raw = payload.lead if payload.lead is not None else {}
        if not raw:
            # flat body (extra fields allowed by the model)
            raw = {k: v for k, v in payload.model_extra.items() if v is not None}
    else:  # pragma: no cover - raw dict body
        raw = payload or {}
        if isinstance(raw.get("lead"), dict):
            raw = raw["lead"]

    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Lead payload must be a JSON object")

    result = build_response(raw)
    log.info("scored lead company=%r -> %s (%s/100, %s)",
             raw.get("company") or raw.get("Company Name"),
             result["lead_classification"], result["lead_score"], result["assessment_source"])
    return JSONResponse(result)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_configured": llm.llm_configured(),
        "scoring": "deterministic-weighted-v1",
    }


@app.get("/api/sample")
def sample():
    """The sample lead from the assignment brief."""
    return {"lead": SAMPLE_LEAD}


SAMPLE_LEAD = {
    "Name": "Rahul Sharma",
    "Company Name": "ABC Technologies",
    "Website": "www.abctechnologies.com",
    "Job Title": "Founder",
    "Industry": "IT Services",
    "Company Location": "Bangalore",
    "Company Size": "50-100 Employees",
    "Lead Source": "Website",
    "Requirement": "Looking for CRM software",
    "Email": "rahul@example.com",
    "Phone": "+91 9876543210",
}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
