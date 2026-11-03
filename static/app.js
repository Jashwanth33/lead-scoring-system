/* Lead scoring UI — plain vanilla JS, no frameworks. */
(function () {
  const $ = (id) => document.getElementById(id);
  const form = $("leadForm");
  const results = $("results");

  const SAMPLE = {
    Name: "Rahul Sharma",
    "Company Name": "ABC Technologies",
    Website: "www.abctechnologies.com",
    "Job Title": "Founder",
    Industry: "IT Services",
    "Company Location": "Bangalore",
    "Company Size": "50-100 Employees",
    "Lead Source": "Website",
    Requirement: "Looking for CRM software",
    Email: "rahul@example.com",
    Phone: "+91 9876543210",
  };

  /* ---------- health chip ---------- */
  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      const chip = $("llmChip");
      chip.textContent = h.llm_configured ? "LLM narrative: Gemini" : "LLM narrative: template fallback";
      chip.classList.toggle("chip-neutral", !h.llm_configured);
    })
    .catch(() => { $("llmChip").textContent = "backend offline"; });

  /* ---------- sample loader ---------- */
  $("sampleBtn").addEventListener("click", () => {
    for (const [name, value] of Object.entries(SAMPLE)) {
      const el = form.elements[name];
      if (el) el.value = value;
    }
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  /* ---------- collect ---------- */
  function collect() {
    const data = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      const v = (el.value || "").trim();
      if (v) data[el.name] = v;
    }
    return data;
  }

  /* ---------- render ---------- */
  function render(res) {
    results.hidden = false;

    // score + colour
    const score = res.lead_score;
    $("scoreValue").textContent = score;
    const gauge = $("gauge");
    gauge.style.setProperty("--v", score);
    const color = score >= 70 ? "var(--green)" : score >= 40 ? "var(--amber)" : "var(--gray)";
    gauge.style.setProperty("--gauge-color", color);

    const badge = $("badge");
    badge.textContent = res.lead_classification.toUpperCase();
    badge.className = "badge " + res.lead_classification.toLowerCase();

    $("confChip").textContent = res.confidence_level + " confidence";
    $("srcChip").textContent = res.assessment_source === "llm" ? "assessment: Gemini" : "assessment: template";
    $("assessment").textContent = res.lead_quality_assessment;

    // breakdown
    $("breakdown").innerHTML = res.score_breakdown
      .map(
        (b) => `
        <div class="brow">
          <span>${b.parameter} <span class="muted">(${b.weight}%)</span></span>
          <span class="bar"><i style="width:${Math.round((b.awarded / b.weight) * 100)}%"></i></span>
          <span class="pts">${b.awarded}/${b.weight}</span>
          <span class="detail">${escapeHtml(b.detail)}</span>
        </div>`
      )
      .join("");

    const fill = (id, items) => {
      const ul = $(id);
      ul.innerHTML = "";
      (items.length ? items : ["— none —"]).forEach((t) => {
        const li = document.createElement("li");
        li.textContent = t;
        ul.appendChild(li);
      });
    };
    fill("positives", res.positive_scoring_factors);
    fill("negatives", res.negative_scoring_factors);

    $("explanation").textContent = res.scoring_explanation;
    $("action").textContent = res.recommended_next_action;
    $("rawJson").textContent = JSON.stringify(res, null, 2);

    results.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  /* ---------- submit ---------- */
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errBox = $("formError");
    errBox.hidden = true;
    const payload = collect();

    if (!Object.keys(payload).length) {
      errBox.textContent = "Enter at least one lead field (or load the sample lead).";
      errBox.hidden = false;
      return;
    }

    const btn = $("scoreBtn");
    btn.disabled = true;
    btn.textContent = "Scoring…";
    try {
      const resp = await fetch("/api/score", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 200)}`);
      }
      render(await resp.json());
    } catch (err) {
      errBox.textContent = "Scoring failed — " + err.message;
      errBox.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Score lead";
    }
  });

  $("clearBtn").addEventListener("click", () => {
    results.hidden = true;
  });
})();
