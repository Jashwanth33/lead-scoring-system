# AI-Based Lead Scoring System

An explainable B2B lead-qualification application: a **deterministic weighted scoring
engine** (0–100) computes the score, and an **LLM (Gemini) writes the narrative
assessment only** — never the score. Identical inputs always produce identical scores.

**Live demo** (deployed on Render): *see repository / Render dashboard*

---

## 1. What it does

For every inbound lead the system returns:

| Output | Source |
|---|---|
| Lead Score (0–100) | Rule-based weighted matrix (`scoring.py`) |
| Lead Classification — Hot / Warm / Cold | Score bands (≥70 / 40–69 / <40) |
| Lead Quality Assessment (2–3 sentences) | Gemini narrative — deterministic template fallback |
| Positive / Negative Scoring Factors | Rule-based bullets from sub-scores |
| Scoring Explanation | Rule-based narrative of every weighted contribution |
| Confidence Level | Field-completeness ratio (High ≥90 %, Med ≥60 %, else Low) |
| Recommended Next Action | Classification playbook (+ enrichment step if Low confidence) |

## 2. Scoring methodology & weightage

| Parameter | Weight | Sub-criteria |
|---|---|---|
| **Firmographics** | **30 %** | Company size **14** (Enterprise 14 · Large MM 13 · MM 12 · MM 50–99 11 · SMB 7 · 10–19 6 · micro 3 · solo 2) · Industry fit **10** (target B2B industries 10, other recognised 5) · Location **6** (priority hub 6, other 4) |
| **Authority / Persona** | **25 %** | C-level/Founder/Owner/Director/VP/Head **25** · Manager/Lead **15** · Individual contributor **6** · Intern/Student **0** |
| **Intent / Requirement** | **30 %** | Explicit buying language ("looking for", pricing, demo, budget, replace, implement…) **30** · Category-level interest (software, platform, tool…) **18** · Informational/research **5** · Ambiguous **6** · Missing **0** |
| **Contact Completeness** | **15 %** | Business-domain email **7** (free provider 1, placeholder/invalid 0) · Valid phone ≥10 digits **4** · Legitimate website domain **4** |

**Classification bands:** Hot ≥ 70 · Warm 40–69 · Cold < 40
**Missing data:** scores 0 for its sub-criterion and is reported as a negative factor —
nothing is ever invented. **Determinism:** `score_lead()` is a pure function — no clock,
no randomness, no network.

## 3. Where the LLM is (and is not) used

```
lead JSON ──► scoring.py (weighted matrix) ──► score 0-100, class, factors,
│                                              explanation, confidence, action
│
└──► llm.py (Gemini, temperature 0) ──► 2-3 sentence lead_quality_assessment
        │                                (only if GEMINI_API_KEY configured;
        └── on any failure ──────────►  deterministic template fallback)
```

The LLM prompt embeds the already-computed score and breakdown and is explicitly told
never to contradict or recompute it. **No key? No network?** The API still answers
100 % of the contract with the template assessment (`assessment_source: "template"`).

## 4. Run locally

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn main:app --reload     # http://127.0.0.1:8000

# optional LLM narratives
echo GEMINI_API_KEY=... > .env      # git-ignored
echo LLM_PROVIDER=gemini >> .env
```

- UI: `http://127.0.0.1:8000/` — form, score gauge, breakdown bars, factors,
  explanation, raw JSON, methodology table. "Load sample lead" fills the brief's sample.
- API docs: `/docs` (OpenAPI)

## 5. API

```http
POST /api/score
{
  "Name": "Rahul Sharma", "Company Name": "ABC Technologies",
  "Job Title": "Founder", "Industry": "IT Services",
  "Company Location": "Bangalore", "Company Size": "50-100 Employees",
  "Website": "www.abctechnologies.com", "Lead Source": "Website",
  "Requirement": "Looking for CRM software",
  "Email": "rahul@example.com", "Phone": "+91 9876543210"
}
```

```json
{
  "lead_score": 90,
  "lead_classification": "Hot",
  "lead_quality_assessment": "...",
  "assessment_source": "llm | template",
  "positive_scoring_factors": ["Authority: High authority title 'Founder' (25/25)", "..."],
  "negative_scoring_factors": ["Email: Placeholder email domain 'example.com' ... (0/7)"],
  "scoring_explanation": "Weighted matrix applied — Firmographics 27/30 ... Total = 90/100 ...",
  "confidence_level": "High",
  "recommended_next_action": "Route immediately to an Account Executive ...",
  "score_breakdown": [{ "parameter": "Firmographics", "weight": 30, "awarded": 27, "detail": "..." }],
  "subscores": { "size": 11, "industry": 10, "location": 6, "authority": 25, "intent": 30, "email": 0, "phone": 4, "website": 4 }
}
```

Other endpoints: `GET /api/health`, `GET /api/sample`.

Field names are forgiving — `Job Title`, `job_title`, `title`… all normalise to the
same canonical field (`normalize_lead`).

## 6. Sample test cases (19 in `tests/test_scoring.py`, all passing)

| # | Case | Expectation |
|---|---|---|
| 1 | Brief's sample lead (Rahul Sharma) | **90/100, Hot, High confidence** (11+10+6+25+30+0+4+4) |
| 2 | Identical inputs, two calls | Byte-identical score, factors, explanation |
| 3 | Empty payload `{}` | 0/100, Cold, Low confidence, no crash |
| 4 | Only title + requirement | Exactly 55/100 (25+30) |
| 5 | gmail vs business email | 1/7 vs 7/7 → 6-point delta |
| 6 | "Marketing Intern" | Authority 0/25 |
| 7 | Manager vs Founder | 15 vs 25 authority |
| 8 | Intent tiers | buying 30 · category 18 · research 5 · empty 0 |
| 9 | Thresholds | 70→Hot, 69→Warm, 40→Warm, 39→Cold |
| 10 | API contract | All 8 required keys + score in 0–100 |
| … | Wrapped `{"lead":{…}}` vs flat body, health, index page | pass |

```bash
pytest -q          # 19 passed
```

## 7. Deploy (Render)

Build: `pip install -r requirements.txt` · Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
Env vars: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY` (secret), `GEMINI_MODEL=gemini-3.8-flash`,
`PYTHON_VERSION=3.11`. Push to `main` → Render auto-deploys.

## 8. Project structure

```
lead-scoring/
├── main.py               # FastAPI app: /api/score, /api/health, /api/sample, UI
├── scoring.py            # ★ deterministic weighted engine (pure function)
├── llm.py                # Gemini narrative layer + template fallback
├── static/               # index.html · style.css · app.js (vanilla UI)
├── tests/test_scoring.py # 19 sample test cases
├── requirements.txt
├── conftest.py
└── README.md             # this document
```
