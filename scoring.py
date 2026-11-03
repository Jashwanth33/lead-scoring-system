"""
Deterministic weighted lead-scoring engine.

RULES OF THE ENGINE
-------------------
* The score (0-100) is computed ONLY by this module — a pure function of the
  input fields. Identical inputs always produce identical scores.
* No LLM, no randomness, no network calls live in this file.
* Weighted matrix (total 100):
      Firmographics .......... 30  (size 14 + industry 10 + location 6)
      Authority / Persona .... 25  (job-title decision power)
      Intent / Requirement ... 30  (clarity + buying signals)
      Contact Completeness ... 15  (business email 7 + phone 4 + website 4)
* Missing fields score 0 for their sub-criterion and are surfaced as negative
  factors — the system never invents data.
* Classification bands:  Hot >= 70 | Warm 40-69 | Cold < 40
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------
# Weight definitions (documented for the scoring methodology)
# --------------------------------------------------------------------------
WEIGHTS = {
    "firmographics": 30,
    "authority": 25,
    "intent": 30,
    "contact": 15,
}
SUB_WEIGHTS = {"size": 14, "industry": 10, "location": 6, "email": 7, "phone": 4, "website": 4}

THRESHOLDS = {"hot": 70, "warm": 40}  # >=70 Hot, >=40 Warm, else Cold

# Canonical field names and the aliases the API accepts for each.
FIELD_ALIASES = {
    "name": ["name", "full_name", "fullname", "contact_name", "lead_name"],
    "company": ["company", "company_name", "companyname", "organisation", "organization"],
    "website": ["website", "web", "company_website", "domain"],
    "title": ["title", "job_title", "jobtitle", "designation", "role"],
    "industry": ["industry", "sector", "company_industry"],
    "location": ["location", "company_location", "city", "region", "geo"],
    "size": ["size", "company_size", "employees", "employee_count", "headcount"],
    "source": ["source", "lead_source", "channel"],
    "requirement": ["requirement", "requirements", "need", "needs", "message", "query", "description"],
    "email": ["email", "email_address", "work_email"],
    "phone": ["phone", "phone_number", "mobile", "contact_number", "telephone"],
}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com",
    "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com",
    "protonmail.com", "proton.me", "gmx.com", "gmx.de", "mail.com",
    "rediffmail.com", "zoho.com", "yandex.com", "inbox.com", "mail.ru",
}

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "tests.com",
    "yoursite.com", "yourdomain.com", "yourwebsite.com", "sample.com",
    "domain.com", "company.com", "placeholder.com", "somedomain.com",
}

TARGET_INDUSTRIES = [
    "it services", "information technology", "software", "saas", "technology",
    "tech", "computer", "internet", "fintech", "banking", "financial",
    "insurance", "healthcare", "hospital", "pharma", "manufacturing", "retail",
    "e-commerce", "ecommerce", "logistics", "supply chain", "education",
    "edtech", "consulting", "professional services", "media", "telecom",
    "telecommunication", "real estate", "energy", "construction", "automotive",
    "travel", "hospitality", "agriculture", "automated", "data", "cloud",
]

# Major business hubs ( metros / tech cities ) — alignment bonus
HUB_LOCATIONS = [
    "bangalore", "bengaluru", "mumbai", "delhi", "ncr", "gurugram", "gurgaon",
    "noida", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad",
    "chandigarh", "coimbatore", "indore", "mohali", "visakhapatnam",
    "singapore", "dubai", "abu dhabi", "sharjah", "qatar", "doha", "riyadh",
    "kuwait", "bahrain", "oman", "london", "manchester", "dublin", "amsterdam",
    "berlin", "paris", "frankfurt", "madrid", "zurich", "stockholm",
    "new york", "san francisco", "bay area", "silicon valley", "seattle",
    "austin", "boston", "chicago", "los angeles", "toronto", "vancouver",
    "sydney", "melbourne", "tokyo", "hong kong", "shanghai", "seoul",
    "bangkok", "kuala lumpur", "jakarta", "manila", "nairobi", "johannesburg",
]

HIGH_TITLES = [
    "founder", "co-founder", "co founder", "ceo", "cto", "coo", "cfo", "cmo",
    "cio", "cro", "chief executive", "chief technology", "chief operating",
    "chief financial", "chief marketing", "chief product", "owner",
    "proprietor", "managing director", "director", "president", "vice president",
    "vp ", " head ", "principal", "partner", "chairman", "chairperson",
    "business owner", "entrepreneur",
]
MEDIUM_TITLES = [
    "manager", "team lead", "lead", "supervisor", "administrator",
    "coordinator", "programme manager", "project manager",
]
LOW_TITLES = [
    "executive", "analyst", "engineer", "developer", "consultant",
    "specialist", "architect", "designer", "freelancer", "associate",
    "account executive", "sales executive", "recruiter", "agent", "staff",
]
COLD_TITLES = [
    "intern", "student", "trainee", "apprentice", "fresher", "volunteer",
]

INTENT_HIGH = [
    "looking for", "looking to", "seeking", "need", "needs", "required",
    "require", "requirement", "want to", "buy", "buying", "purchase",
    "procure", "procurement", "pricing", "price", "quote", "quotation",
    "demo", "demonstration", "trial", "pilot", "budget", "timeline", "rfp",
    "evaluate", "evaluation", "comparing", "comparison", "switch",
    "switching", "replace", "replacement", "migration", "implement",
    "implementation", "rollout", "roll out", "deploy", "sign up", "subscribe",
    "subscription", "onboard", "ready to",
]
INTENT_MEDIUM = [
    "software", "platform", "solution", "tool", "tools", "system",
    "service", "services", "api", "automation", "license", "licence",
    "crm", "erp", "saas", "integration", "setup", "set up", "custom",
    "development", "dashboard", "analytics",
]
INTENT_LOW = [
    "information", "informational", "details", "brochure", "curious",
    "just checking", "exploring", "future", "someday", "no rush",
    "research", "learning", "course", "assignment",
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$", re.I)
RANGE_RE = re.compile(r"(\d[\d,]*)\s*(?:-|–|—|to|till|\+)\s*(\d[\d,]*)", re.I)
BARE_NUM_RE = re.compile(r"(\d[\d,]*)")


# --------------------------------------------------------------------------
# Input normalisation
# --------------------------------------------------------------------------
def _norm_key(k: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(k).strip().lower())


def normalize_lead(raw: dict) -> dict:
    """Map arbitrary incoming keys onto canonical field names."""
    incoming = {_norm_key(k): v for k, v in (raw or {}).items()}
    out = {}
    for canonical, aliases in FIELD_ALIASES.items():
        value = None
        for alias in aliases:
            if alias in incoming and incoming[alias] not in (None, ""):
                value = incoming[alias]
                break
        if value is None:
            # last chance: fuzzy contains match (e.g. "Company Name (Website)")
            for key, val in incoming.items():
                if val not in (None, "") and any(a in key for a in aliases):
                    value = val
                    break
        out[canonical] = str(value).strip() if value not in (None, "") else ""
    return out


def _clean_text(value: str) -> str:
    """Normalise unicode punctuation so '50–100' == '50-100'."""
    return unicodedata.normalize("NFKC", value or "")


# --------------------------------------------------------------------------
# Sub-scorers
# --------------------------------------------------------------------------
def score_size(size: str) -> tuple[int, str]:
    """Company size -> 0..14 (ranges evaluated by their midpoint)."""
    text = _clean_text(size).lower()
    if not text:
        return 0, "Company size not provided (0/14)"
    lo = hi = None
    m = RANGE_RE.search(text)
    if m:
        lo, hi = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
    else:
        m2 = BARE_NUM_RE.search(text)
        if m2:
            lo = hi = int(m2.group(1).replace(",", ""))
    if "solo" in text or "freelance" in text or "individual" in text or (hi is not None and hi <= 1):
        return 2, "Solo / individual contributor (2/14)"
    if "enterprise" in text or "large" in text:
        return 14, "Enterprise segment (14/14)"
    if lo is None:
        return 0, f"Unrecognised size value '{size}' (0/14)"
    mid = (lo + hi) / 2
    if mid >= 1000:
        pts, label = 14, "Enterprise (1000+)"
    elif mid >= 250:
        pts, label = 13, "Large mid-market (250-999)"
    elif mid >= 100:
        pts, label = 12, "Mid-market (100-249)"
    elif mid >= 50:
        pts, label = 11, "Mid-market (50-99)"
    elif mid >= 20:
        pts, label = 7, "SMB (20-49)"
    elif mid >= 10:
        pts, label = 6, "Small business (10-19)"
    elif mid >= 2:
        pts, label = 3, "Micro team (2-9)"
    else:
        pts, label = 2, "Solo (1)"
    return pts, f"{label} — {size} ({pts}/14)"


def score_industry(industry: str) -> tuple[int, str]:
    text = _clean_text(industry).lower()
    if not text:
        return 0, "Industry not provided (0/10)"
    if any(t in text for t in TARGET_INDUSTRIES):
        return 10, f"Target industry '{industry}' (10/10)"
    return 5, f"Recognised but non-core industry '{industry}' (5/10)"


def score_location(location: str) -> tuple[int, str]:
    text = _clean_text(location).lower()
    if not text:
        return 0, "Location not provided (0/6)"
    if any(h in text for h in HUB_LOCATIONS):
        return 6, f"Priority hub market '{location}' (6/6)"
    return 4, f"Valid location '{location}' (4/6)"


def score_authority(title: str) -> tuple[int, str]:
    text = f" {_clean_text(title).lower()} "
    if not text.strip():
        return 0, "Job title missing — authority unknown (0/25)"
    if any(c in text for c in COLD_TITLES):
        return 0, f"Cold persona '{title.strip()}' — no decision power (0/25)"
    if any(h in text for h in HIGH_TITLES):
        return 25, f"High authority title '{title.strip()}' (25/25)"
    if any(m in text for m in MEDIUM_TITLES):
        return 15, f"Manager-level persona '{title.strip()}' (15/25)"
    if any(lo in text for lo in LOW_TITLES):
        return 6, f"Individual contributor '{title.strip()}' — influencer only (6/25)"
    return 6, f"Non-decision title '{title.strip()}' (6/25)"


def score_intent(requirement: str) -> tuple[int, str]:
    text = _clean_text(requirement).lower()
    if not text:
        return 0, "No requirement captured — intent unknown (0/30)"
    if any(k in text for k in INTENT_HIGH):
        return 30, f"Explicit buying intent: “{requirement.strip()[:80]}” (30/30)"
    if any(k in text for k in INTENT_MEDIUM):
        return 18, f"Category-level interest without buying signals (18/30)"
    if any(k in text for k in INTENT_LOW):
        return 5, f"Low intent — informational / research query (5/30)"
    return 6, f"Ambiguous requirement, no buying signals matched (6/30)"


def score_email(email: str) -> tuple[int, str]:
    text = _clean_text(email).lower().strip()
    if not text:
        return 0, "Email missing (0/7)"
    if not EMAIL_RE.match(text):
        return 0, f"Invalid email format '{email}' (0/7)"
    domain = text.split("@", 1)[1]
    if domain in PLACEHOLDER_DOMAINS:
        return 0, f"Placeholder email domain '{domain}' — not a real business address (0/7)"
    if domain in FREE_EMAIL_DOMAINS:
        return 1, f"Generic email provider '{domain}' instead of a business domain (1/7)"
    return 7, f"Valid business-domain email (7/7)"


def score_phone(phone: str) -> tuple[int, str]:
    text = _clean_text(phone)
    if not text:
        return 0, "Phone missing (0/4)"
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        return 4, f"Valid phone number ({len(digits)} digits) (4/4)"
    return 0, f"Phone looks incomplete ({len(digits)} digits) (0/4)"


def score_website(website: str) -> tuple[int, str]:
    text = _clean_text(website).lower().strip()
    if not text:
        return 0, "Website missing (0/4)"
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0].split("?")[0]
    if not DOMAIN_RE.match(text):
        return 0, f"Invalid website domain '{website}' (0/4)"
    if text in PLACEHOLDER_DOMAINS:
        return 1, f"Placeholder domain '{text}' (1/4)"
    return 4, f"Legitimate company website '{text}' (4/4)"


# --------------------------------------------------------------------------
# Composite scoring
# --------------------------------------------------------------------------
def classify(score: int) -> str:
    if score >= THRESHOLDS["hot"]:
        return "Hot"
    if score >= THRESHOLDS["warm"]:
        return "Warm"
    return "Cold"


def confidence_for(lead: dict) -> str:
    fields = list(FIELD_ALIASES.keys())
    present = sum(1 for f in fields if lead.get(f))
    ratio = present / len(fields)
    if ratio >= 0.90:
        return "High"
    if ratio >= 0.60:
        return "Medium"
    return "Low"


NEXT_ACTIONS = {
    "Hot": (
        "Route immediately to an Account Executive for a 15-minute discovery call "
        "within 2 hours; lead the conversation with their stated requirement."
    ),
    "Warm": (
        "Add to the 5-day email + call nurture sequence and assign an SDR to qualify "
        "budget and timeline within 48 hours."
    ),
    "Cold": (
        "Keep out of active outbound: enroll in the monthly educational drip and "
        "re-score automatically on the next website or email engagement."
    ),
}


def score_lead(raw: dict) -> dict:
    """Pure, deterministic scoring function. Same input -> same output."""
    lead = normalize_lead(raw)

    size_pts, size_detail = score_size(lead["size"])
    ind_pts, ind_detail = score_industry(lead["industry"])
    loc_pts, loc_detail = score_location(lead["location"])
    firm_pts = size_pts + ind_pts + loc_pts

    auth_pts, auth_detail = score_authority(lead["title"])
    intent_pts, intent_detail = score_intent(lead["requirement"])

    email_pts, email_detail = score_email(lead["email"])
    phone_pts, phone_detail = score_phone(lead["phone"])
    web_pts, web_detail = score_website(lead["website"])
    contact_pts = email_pts + phone_pts + web_pts

    total = firm_pts + auth_pts + intent_pts + contact_pts
    total = max(0, min(100, total))
    classification = classify(total)
    confidence = confidence_for(lead)

    # ---- positive / negative factor bullets (deterministic) ----
    positives, negatives = [], []

    def add(detail: str, pts: int, cap: int, name: str):
        if pts == cap and pts > 0:
            positives.append(f"{name}: {detail}")
        elif pts == 0 and cap > 0:
            negatives.append(f"{name}: {detail}")
        elif pts < cap * 0.5:
            negatives.append(f"{name}: {detail}")
        elif pts > 0:
            positives.append(f"{name}: {detail}")

    add(size_detail, size_pts, SUB_WEIGHTS["size"], "Company size")
    add(ind_detail, ind_pts, SUB_WEIGHTS["industry"], "Industry fit")
    add(loc_detail, loc_pts, SUB_WEIGHTS["location"], "Location alignment")
    add(auth_detail, auth_pts, WEIGHTS["authority"], "Authority")
    add(intent_detail, intent_pts, WEIGHTS["intent"], "Intent")
    add(email_detail, email_pts, SUB_WEIGHTS["email"], "Email")
    add(phone_detail, phone_pts, SUB_WEIGHTS["phone"], "Phone")
    add(web_detail, web_pts, SUB_WEIGHTS["website"], "Website")

    if lead["source"]:
        positives.append(f"Lead captured via '{lead['source']}' (attribution known)")
    if not lead["name"]:
        negatives.append("Contact name missing — personalisation will be limited")
    if not lead["company"]:
        negatives.append("Company name missing — account research not possible")

    # ---- transparent narrative explanation ----
    explanation = (
        f"Weighted matrix applied — Firmographics {firm_pts}/{WEIGHTS['firmographics']} "
        f"(size {size_pts}/14, industry {ind_pts}/10, location {loc_pts}/6); "
        f"Authority {auth_pts}/{WEIGHTS['authority']}; "
        f"Intent {intent_pts}/{WEIGHTS['intent']}; "
        f"Contact completeness {contact_pts}/{WEIGHTS['contact']} "
        f"(email {email_pts}/7, phone {phone_pts}/4, website {web_pts}/4). "
        f"Total = {total}/100. Bands: Hot >= {THRESHOLDS['hot']}, "
        f"Warm >= {THRESHOLDS['warm']}, else Cold → classified {classification.upper()} "
        f"with {confidence.lower()} confidence based on field completeness."
    )

    # ---- recommended action ----
    action = NEXT_ACTIONS[classification]
    if confidence == "Low":
        action = (
            "Enrich missing fields (data-enrichment pass) before any outreach, then "
            "re-score; " + action[0].lower() + action[1:]
        )

    breakdown = [
        {"parameter": "Firmographics", "weight": 30, "awarded": firm_pts,
         "detail": f"{size_detail}; {ind_detail}; {loc_detail}"},
        {"parameter": "Authority / Persona", "weight": 25, "awarded": auth_pts, "detail": auth_detail},
        {"parameter": "Intent / Requirement", "weight": 30, "awarded": intent_pts, "detail": intent_detail},
        {"parameter": "Contact Completeness", "weight": 15, "awarded": contact_pts,
         "detail": f"{email_detail}; {phone_detail}; {web_detail}"},
    ]

    return {
        "lead_score": total,
        "lead_classification": classification,
        "positive_scoring_factors": positives,
        "negative_scoring_factors": negatives,
        "scoring_explanation": explanation,
        "confidence_level": confidence,
        "recommended_next_action": action,
        "_normalized_lead": lead,
        "_breakdown": breakdown,
        "_subscores": {
            "size": size_pts, "industry": ind_pts, "location": loc_pts,
            "authority": auth_pts, "intent": intent_pts,
            "email": email_pts, "phone": phone_pts, "website": web_pts,
        },
    }


def deterministic_assessment(result: dict) -> str:
    """Template fallback for lead_quality_assessment when no LLM is available."""
    lead = result["_normalized_lead"]
    who = lead["name"] or "Unknown contact"
    org = lead["company"] or "an unlisted company"
    title = lead["title"] or "unknown role"
    subs = result["_subscores"]
    intent_word = {
        30: "clear buying intent",
        18: "category-level interest but no explicit buying signal",
        5: "only informational interest",
        6: "ambiguous intent",
        0: "no captured requirement",
    }[subs["intent"]]
    contact_word = {
        15: "complete contact details",
        0: "no usable contact details",
    }.get(result["_subscores"]["email"] + result["_subscores"]["phone"] + result["_subscores"]["website"],
          "partial contact details")
    return (
        f"{who} ({title}) at {org} scores {result['lead_score']}/100 — a "
        f"{result['lead_classification']} lead with {intent_word} and {contact_word}. "
        f"{'Prioritise ' + ('same-day outreach' if result['lead_classification'] == 'Hot' else 'nurture-track follow-up' if result['lead_classification'] == 'Warm' else 'low-touch re-engagement')}, "
        f"confidence {result['confidence_level'].lower()} based on input completeness."
    )
