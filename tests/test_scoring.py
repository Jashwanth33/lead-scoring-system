"""
Sample test cases for the deterministic scoring engine + API contract.

Run: pytest -q
"""

from __future__ import annotations

import pytest

import scoring
from scoring import classify, normalize_lead, score_lead
from main import SAMPLE_LEAD, app, build_response

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    pytest.skip("fastapi testclient unavailable", allow_module_level=True)

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Sample lead from the assignment brief
# ---------------------------------------------------------------------------
def test_sample_lead_score_and_classification():
    r = score_lead(SAMPLE_LEAD)
    # size 50-100 -> 11 | IT Services -> 10 | Bangalore -> 6
    # Founder -> 25 | "Looking for CRM software" -> 30
    # example.com -> 0 | phone -> 4 | website -> 4
    assert r["lead_score"] == 90
    assert r["lead_classification"] == "Hot"
    assert r["confidence_level"] == "High"
    assert r["_subscores"]["authority"] == 25
    assert r["_subscores"]["intent"] == 30


# ---------------------------------------------------------------------------
# 2. Determinism — identical input produces identical output
# ---------------------------------------------------------------------------
def test_deterministic_for_identical_inputs():
    a = score_lead(SAMPLE_LEAD)
    b = score_lead(dict(SAMPLE_LEAD))
    assert a["lead_score"] == b["lead_score"]
    assert a["lead_classification"] == b["lead_classification"]
    assert a["positive_scoring_factors"] == b["positive_scoring_factors"]
    assert a["scoring_explanation"] == b["scoring_explanation"]


# ---------------------------------------------------------------------------
# 3. Missing / empty data handled gracefully
# ---------------------------------------------------------------------------
def test_empty_lead_scores_zero_cold_low():
    r = score_lead({})
    assert r["lead_score"] == 0
    assert r["lead_classification"] == "Cold"
    assert r["confidence_level"] == "Low"
    assert any("missing" in f.lower() for f in r["negative_scoring_factors"])


def test_partial_lead_only_scores_provided_fields():
    r = score_lead({"Job Title": "Founder", "Requirement": "Need CRM pricing and a demo"})
    assert r["_subscores"]["authority"] == 25
    assert r["_subscores"]["intent"] == 30
    assert r["_subscores"]["email"] == 0
    assert r["lead_score"] == 25 + 30
    assert r["confidence_level"] == "Low"


# ---------------------------------------------------------------------------
# 4. Weight rules
# ---------------------------------------------------------------------------
def test_free_email_loses_points_vs_business_domain():
    base = dict(SAMPLE_LEAD)
    generic = score_lead({**base, "Email": "rahul@gmail.com"})
    business = score_lead({**base, "Email": "rahul@abctechnologies.com"})
    assert generic["_subscores"]["email"] == 1
    assert business["_subscores"]["email"] == 7
    assert business["lead_score"] - generic["lead_score"] == 6
    assert any("Generic email" in f for f in generic["negative_scoring_factors"])


def test_intern_is_cold_persona():
    r = score_lead({**SAMPLE_LEAD, "Job Title": "Marketing Intern"})
    assert r["_subscores"]["authority"] == 0


def test_manager_vs_founder_authority():
    manager = score_lead({**SAMPLE_LEAD, "Job Title": "Marketing Manager"})
    founder = score_lead({**SAMPLE_LEAD, "Job Title": "Founder"})
    assert manager["_subscores"]["authority"] == 15
    assert founder["_subscores"]["authority"] == 25


def test_intent_tiers():
    high = score_lead({**SAMPLE_LEAD, "Requirement": "Looking for CRM software"})
    medium = score_lead({**SAMPLE_LEAD, "Requirement": "Curious about your software"})
    low = score_lead({**SAMPLE_LEAD, "Requirement": "Just gathering information for a course"})
    none = score_lead({**SAMPLE_LEAD, "Requirement": ""})
    assert high["_subscores"]["intent"] == 30
    assert medium["_subscores"]["intent"] == 18
    assert low["_subscores"]["intent"] == 5
    assert none["_subscores"]["intent"] == 0


def test_classification_thresholds():
    assert classify(70) == "Hot"
    assert classify(69) == "Warm"
    assert classify(40) == "Warm"
    assert classify(39) == "Cold"


def test_score_always_within_bounds():
    hot = score_lead(SAMPLE_LEAD)
    assert 0 <= hot["lead_score"] <= 100
    huge = score_lead({**SAMPLE_LEAD, "Company Size": "100000", "Requirement": "need buy pricing demo"})
    assert 0 <= huge["lead_score"] <= 100


# ---------------------------------------------------------------------------
# 5. Input handling
# ---------------------------------------------------------------------------
def test_alias_keys_normalise():
    lead = normalize_lead({"job_title": "CEO", "companyName": "Acme", "Full Name": "A B"})
    assert lead["title"] == "CEO"
    assert lead["company"] == "Acme"
    assert lead["name"] == "A B"


def test_handle_missing_size_values():
    assert score_lead({**SAMPLE_LEAD, "Company Size": "n/a"})["_subscores"]["size"] in (0, 2)


# ---------------------------------------------------------------------------
# 6. API contract
# ---------------------------------------------------------------------------
def test_api_sample_endpoint():
    resp = client.get("/api/sample")
    assert resp.status_code == 200
    assert resp.json()["lead"]["Name"] == "Rahul Sharma"


def test_api_score_returns_required_keys():
    resp = client.post("/api/score", json=SAMPLE_LEAD)
    assert resp.status_code == 200
    body = resp.json()
    required = [
        "lead_score", "lead_classification", "lead_quality_assessment",
        "positive_scoring_factors", "negative_scoring_factors",
        "scoring_explanation", "confidence_level", "recommended_next_action",
    ]
    for key in required:
        assert key in body, f"missing {key}"
    assert isinstance(body["lead_score"], int)
    assert body["lead_classification"] in ("Hot", "Warm", "Cold")
    assert body["confidence_level"] in ("High", "Medium", "Low")
    assert len(body["lead_quality_assessment"]) > 40


def test_api_score_deterministic_across_calls():
    a = client.post("/api/score", json=SAMPLE_LEAD).json()
    b = client.post("/api/score", json=SAMPLE_LEAD).json()
    assert a["lead_score"] == b["lead_score"]
    assert a["scoring_explanation"] == b["scoring_explanation"]
    assert a["positive_scoring_factors"] == b["positive_scoring_factors"]
    assert a["recommended_next_action"] == b["recommended_next_action"]


def test_api_accepts_wrapped_and_flat_payloads():
    flat = client.post("/api/score", json=SAMPLE_LEAD).json()
    wrapped = client.post("/api/score", json={"lead": SAMPLE_LEAD}).json()
    assert flat["lead_score"] == wrapped["lead_score"]


def test_api_empty_object_does_not_crash():
    resp = client.post("/api/score", json={})
    assert resp.status_code == 200
    assert resp.json()["lead_score"] == 0


def test_api_health_and_index():
    assert client.get("/api/health").status_code == 200
    home = client.get("/")
    assert home.status_code == 200
    assert b"AI Lead Scoring" in home.content


def test_build_response_assessment_fallback_shape():
    out = build_response(SAMPLE_LEAD)
    assert out["assessment_source"] in ("llm", "template")
    assert len(out["score_breakdown"]) == 4
    assert sum(b["weight"] for b in out["score_breakdown"]) == 100
