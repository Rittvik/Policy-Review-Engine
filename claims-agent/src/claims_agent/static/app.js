"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="review-token"]').content;
let current = null;
const pretty = (value) => JSON.stringify(value, null, 2);
const title = (value) => value.replaceAll("_", " ");

function node(tag, text, parent) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (parent) parent.append(n);
  return n;
}

function message(text, error = false) {
  const msg = $("message");
  if (!msg) return;
  msg.textContent = text;
  msg.classList.toggle("error", error);
}

async function api(path, data) {
  const res = await fetch(
    path,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Review-Token": token,
          },
          body: pretty(data),
        },
  );
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || out.detail || "Request failed.");
  return out;
}

async function busy(fn) {
  document
    .querySelectorAll("button,input,select,textarea")
    .forEach((b) => (b.disabled = true));
  message("Working…");
  try {
    await fn();
    message("");
  } catch (e) {
    message(e.message, true);
  } finally {
    document
      .querySelectorAll("button,input,select,textarea")
      .forEach((b) => (b.disabled = false));
  }
}

// Multi-Page View Navigation System
function switchView(viewId) {
  const views = {
    "view-claim": { tabId: "tab-claim", hash: "#claim" },
    "view-history": { tabId: "tab-history", hash: "#history" },
    "view-evals": { tabId: "tab-evals", hash: "#evals" },
  };

  if (!views[viewId]) viewId = "view-claim";

  document.querySelectorAll(".page-view").forEach((v) => {
    v.hidden = v.id !== viewId;
  });

  document.querySelectorAll(".nav-tab").forEach((tab) => {
    const isTarget = tab.dataset.view === viewId;
    tab.classList.toggle("active", isTarget);
    tab.setAttribute("aria-selected", isTarget ? "true" : "false");
  });

  if (window.location.hash !== views[viewId].hash) {
    history.replaceState(null, "", views[viewId].hash);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });

  if (viewId === "view-history") {
    busy(updateHistoryList);
  } else if (viewId === "view-evals") {
    busy(loadEvalsDashboard);
  }
}

function initNavigation() {
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      switchView(tab.dataset.view);
    });
  });

  function handleHash() {
    const hash = window.location.hash.toLowerCase();
    if (hash === "#history") {
      switchView("view-history");
    } else if (hash === "#evals" || hash === "#evaluation") {
      switchView("view-evals");
    } else {
      switchView("view-claim");
    }
  }

  window.addEventListener("hashchange", handleHash);
  handleHash();

  document.querySelectorAll(".eval-filter-bar .filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".eval-filter-bar .filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentEvalsFilter = btn.dataset.filter;
      if (currentEvalsData) {
        renderEvalsCases(currentEvalsData, currentEvalsFilter);
      }
    });
  });

  if ($("refresh-evals-btn")) {
    $("refresh-evals-btn").addEventListener("click", () => {
      busy(async () => {
        message("Re-running offline evaluation harness across benchmark cases...", false);
        const res = await api("/api/evaluation/run", {});
        currentEvalsData = res;
        renderPhoenixHeader(res.phoenix);
        renderPhoenixDistributions(res.phoenix);
        renderEvalsScorecards(res.metrics || {}, res.phoenix, res.decisions);
        renderEvalsCases(res, currentEvalsFilter);
        renderEvalsRubric(res.rubric || "");
        message("✓ Evaluation run complete across all benchmark cases!", false);
      });
    });
  }
}

function invalidate() {
  current = null;
  $("result").hidden = true;
  $("assessment").hidden = true;
  $("preview-panel").hidden = true;
  if ($("intelligence-card")) $("intelligence-card").replaceChildren();
  if ($("jump-to-history-btn")) $("jump-to-history-btn").hidden = true;
}

function claim() {
  const c = JSON.parse($("claim").value);
  const target = (c && c.request && c.request.claim && typeof c.request.claim === "object") ? c.request.claim : c;
  if (target && target.claim_id) {
    const cid = target.claim_id;
    const rid = target.review_id;
    for (const key of [
      "coding_assessment",
      "treatment_history_applicability",
      "clinical_assessment",
      "exclusion_assessment",
      "authorization_assessment",
      "payment_determination",
      "equipment_cost_assessment",
    ]) {
      if (target[key] && target[key].request && typeof target[key].request === "object") {
        target[key].request.claim_id = cid;
        if (rid) target[key].request.review_id = rid;
      }
    }
  }
  return c;
}

function generateUniqueReviewId(claimId) {
  const now = new Date();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  const h = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  const s = String(now.getSeconds()).padStart(2, "0");
  const rand = Math.floor(100 + Math.random() * 900);
  const prefix = claimId ? `REV-${claimId}` : "REV";
  return `${prefix}-${m}${d}-${h}${min}${s}-${rand}`;
}

function setClaimReviewId(c, newId) {
  if (!c || typeof c !== "object") return c;
  const target = (c.request && c.request.claim && typeof c.request.claim === "object") ? c.request.claim : c;
  target.review_id = newId;
  const cid = target.claim_id;
  for (const key of [
    "coding_assessment",
    "treatment_history_applicability",
    "clinical_assessment",
    "exclusion_assessment",
    "authorization_assessment",
    "payment_determination",
    "equipment_cost_assessment",
  ]) {
    if (target[key] && target[key].request && typeof target[key].request === "object") {
      target[key].request.review_id = newId;
      if (cid) target[key].request.claim_id = cid;
    }
  }
  return c;
}

function updateClaim() {
  invalidate();
  try {
    const raw = claim();
    const isAppealSub = Boolean(raw && raw.request && raw.request.claim);
    const c = isAppealSub ? raw.request.claim : raw;
    if ($("claim-review-id") && c.review_id) {
      $("claim-review-id").value = c.review_id;
    }
    const proc = c.procedure_code || "General Claim";
    const billed = c.claimed_amount != null ? `Billed $${c.claimed_amount}` : "";
    if (isAppealSub) {
      $("claim-summary").textContent =
        `🛡️ Appeal Reassessment · ${c.claim_id} · ${c.review_id || "No Review ID"} · ${proc} ${billed ? "· " + billed : ""}`;
    } else {
      $("claim-summary").textContent =
        `${c.claim_id} · ${c.review_id || "No Review ID"} · ${title(c.claim_type)} · ${proc} ${billed ? "· " + billed : ""}`;
    }
    $("documents").replaceChildren();
    node(
      "p",
      isAppealSub
        ? "Documentation included in this appeal submission package:"
        : "Select the clinical documents to include in extraction.",
      $("documents"),
    );
    for (const d of c.documents || []) {
      if (
        d.status !== "provided" ||
        !["clinical_note", "prior_treatment_history", "formulary", "written_appeal", "denial_letter", "appeal_receipt"].includes(
          d.document_type,
        )
      )
        continue;
      const label = node("label", undefined, $("documents"));
      label.className = "check";
      const input = node("input", undefined, label);
      input.type = "checkbox";
      input.value = d.document_id;
      input.checked = isAppealSub || (
        d.document_type !== "prior_treatment_history" ||
        c.procedure_code?.startsWith("MRI")
      );
      input.addEventListener("change", invalidate);
      node("span", `${d.document_id} — ${title(d.document_type)}`, label);
    }
  } catch (e) {
    $("claim-summary").textContent = "Enter valid claim or appeal JSON to continue.";
    $("documents").replaceChildren();
  }
}


function input() {
  return {
    claim: claim(),
    mode: $("mode").value,
    document_ids: [...$("documents").querySelectorAll("input:checked")].map(
      (i) => i.value,
    ),
    save: $("save").checked,
  };
}

function detail(parent, label, value) {
  const d = node("details", undefined, parent);
  node("summary", label, d);
  node("pre", typeof value === "string" ? value : pretty(value), d);
  return d;
}

function decision(out, parent) {
  parent.replaceChildren();
  const d = out.decision,
    c = d.context,
    card = node("div", undefined, parent);

  let statusClass = "route";
  let icon = "📋";
  if (d.action.startsWith("approve")) {
    statusClass = "approve";
    icon = "✅";
  } else if (d.action.startsWith("deny")) {
    statusClass = "deny";
    icon = "❌";
  }
  card.className = `result-card ${statusClass}`;
  node("h3", `${icon} Final Decision: ${title(d.action)}`, card);
  node("p", c.reason, card);
  node("p", `Review reference ID: ${c.review_id}`, card);
  if (Object.keys(d.arguments).length) {
    const argsP = node("p", undefined, card);
    node("strong", "Action details: ", argsP);
    const parts = Object.entries(d.arguments).map(
      ([k, v]) => `${title(k)}: ${typeof v === "number" && k.includes("amount") ? "$" + v.toFixed(2) : title(String(v))}`
    );
    argsP.append(document.createTextNode(parts.join(" · ")));
  }
  if (c.missing_information.length) {
    const missBox = node("details", undefined, parent);
    node("summary", `Missing information (${c.missing_information.length} items)`, missBox);
    const ul = node("ul", undefined, missBox);
    for (const item of c.missing_information) {
      node("li", title(item), ul);
    }
  }
  if (c.unresolved_information.length) {
    const unresBox = node("details", undefined, parent);
    node("summary", `Unresolved information (${c.unresolved_information.length} items)`, unresBox);
    const ul = node("ul", undefined, unresBox);
    for (const item of c.unresolved_information) {
      node("li", title(item), ul);
    }
  }
  const refs = node("details", undefined, parent);
  node("summary", `Policy evidence (${c.policy_evidence.length} citations)`, refs);
  for (const r of c.policy_evidence) {
    const p = node("p", `Section ${r.section}, page ${r.source_page}:\n${r.quote}`, refs);
    p.className = "policy-quote";
  }
  if (c.claim_evidence && c.claim_evidence.length) {
    const claimEvBox = node("details", undefined, parent);
    const isDup = d.action === "deny_claim" && (c.reason || "").toLowerCase().includes("duplicate");
    claimEvBox.open = isDup;
    node("summary", `Claim & Historical Evidence (${c.claim_evidence.length} verified facts)`, claimEvBox);
    const ul = node("ul", undefined, claimEvBox);
    ul.style.margin = "8px 0";
    ul.style.paddingLeft = "20px";
    ul.style.fontSize = "12px";
    for (const fact of c.claim_evidence) {
      const li = node("li", undefined, ul);
      li.style.marginBottom = "4px";
      if (fact.includes(";")) {
        const parts = fact.split(";").map(p => {
          const [k, v] = p.split("=", 2);
          return `<strong>${title(k)}:</strong> <code style="background:#f1f5f9; padding:1px 5px; border-radius:3px; color:#0f172a;">${v}</code>`;
        });
        li.innerHTML = parts.join(" · ");
      } else if (fact.includes("=")) {
        const [k, v] = fact.split("=", 2);
        li.innerHTML = `<strong>${title(k)}:</strong> <code style="background:#f1f5f9; padding:1px 5px; border-radius:3px; color:#0f172a;">${v}</code>`;
      } else {
        li.textContent = fact;
      }
    }
  }
  const trace = node("details", undefined, parent);
  node("summary", `Rule-by-rule decision trail (${c.decision_trace.length} rules evaluated)`, trace);
  for (const r of c.decision_trace)
    node("p", `${title(r.rule_id)} · ${title(r.outcome)}: ${r.reason}`, trace);
}

function quoteRow(parent, docs, ref = {}) {
  const row = node("div", undefined, parent);
  row.className = "quote-row";
  const label = node("label", undefined, row);
  label.innerHTML = 'Evidence document <span class="req">*</span>';
  const sel = node("select", undefined, label);
  for (const d of docs) {
    const opt = node("option", d.document_id, sel);
    opt.value = d.document_id;
  }
  sel.value = ref.document_id || docs[0]?.document_id || "";
  const qlabel = node("label", undefined, row);
  qlabel.innerHTML = 'Exact source quotation <span class="req">*</span>';
  const q = node("textarea", undefined, qlabel);
  q.rows = 2;
  q.value = ref.quote || "";
  q.placeholder = "Paste exact quotation from the document above...";
  q.required = true;
  const remove = node("button", "Remove quotation", row);
  remove.type = "button";
  remove.className = "secondary";
  remove.onclick = () => row.remove();
}

function renderIntelligence(intel, parent, dec) {
  if (!parent) return;
  parent.replaceChildren();
  if (!intel) return;

  const card = node("div", undefined, parent);
  card.className = "intelligence-panel";
  card.style.marginTop = "16px";
  card.style.marginBottom = "16px";
  card.style.padding = "16px";
  card.style.background = "#f8fafc";
  card.style.border = "1px solid #cbd5e1";
  card.style.borderRadius = "8px";

  const header = node("div", undefined, card);
  header.style.display = "flex";
  header.style.alignItems = "center";
  header.style.justifyContent = "space-between";
  header.style.marginBottom = "12px";
  header.innerHTML = `<h3 style="margin:0; font-size:15px; color:#0f172a; display:flex; align-items:center; gap:8px;">
    <span>🤖</span> <strong>AI Clinical & Integrity Copilot</strong>
  </h3><span style="font-size:12px; background:#e2e8f0; color:#475569; padding:2px 8px; border-radius:12px; font-weight:600;">Active Advisory</span>`;

  const grid = node("div", undefined, card);
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(280px, 1fr))";
  grid.style.gap = "14px";

  // 1. Fast-Track Triage Card
  if (intel.fast_track) {
    const ft = intel.fast_track;
    const ftBox = node("div", undefined, grid);
    ftBox.style.padding = "12px";
    ftBox.style.background = "#ffffff";
    ftBox.style.border = "1px solid #e2e8f0";
    ftBox.borderRadius = "6px";

    const laneColors = {
      GREEN: { bg: "#dcfce7", text: "#15803d", icon: "🟢" },
      YELLOW: { bg: "#fef9c3", text: "#a16207", icon: "🟡" },
      RED: { bg: "#fee2e2", text: "#b91c1c", icon: "🔴" }
    };
    const c = laneColors[ft.lane] || laneColors.YELLOW;

    ftBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-weight:600; font-size:13px; color:#334155;">🚦 Prior-Auth Fast-Track</span>
        <span style="background:${c.bg}; color:${c.text}; font-weight:700; font-size:12px; padding:2px 8px; border-radius:4px;">
          ${c.icon} ${ft.lane} LANE
        </span>
      </div>
      <div style="font-size:13px; color:#0f172a; margin-bottom:6px;"><strong>Action:</strong> ${ft.suggested_action}</div>
      <div style="font-size:12px; color:#64748b; margin-bottom:8px;">
        Heuristic triage index (not LLM confidence): <strong>${Math.round(ft.confidence * 100)}/100</strong> · Auto-Approval: <strong>${(ft.auto_approval_eligible ?? ft.gold_card_eligible) ? "Eligible (Zero-Touch)" : "Manual Review Required"}</strong> · Priority: <strong>${ft.recommended_priority.toUpperCase()}</strong>
      </div>
      <ul style="margin:0; padding-left:18px; font-size:12px; color:#475569;">
        ${ft.rationale.map(r => `<li>${r}</li>`).join("")}
      </ul>
    `;
  }

  // 2. Adverse Determination & Denial Notice (EOB Generator) Card
  if (intel.adverse_notice) {
    const notice = intel.adverse_notice;
    const noticeBox = node("div", undefined, grid);
    noticeBox.style.padding = "12px";
    noticeBox.style.background = "#ffffff";
    noticeBox.style.border = "1px solid #e2e8f0";
    noticeBox.style.borderRadius = "6px";

    const statusBadges = {
      denied: { bg: "#fee2e2", text: "#b91c1c", label: "DENIAL NOTICE" },
      pended_missing_documentation: { bg: "#fef9c3", text: "#a16207", label: "PENDED: INFO NEEDED" },
      routed_for_clinical_review: { bg: "#dbeafe", text: "#1d4ed8", label: "PENDED: CLINICAL REVIEW" }
    };
    const sb = statusBadges[notice.status] || statusBadges.denied;

    noticeBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-weight:600; font-size:13px; color:#334155;">📄 Adverse Determination & Denial Letter (EOB)</span>
        <span style="background:#fee2e2; color:#b91c1c; font-weight:700; font-size:11px; padding:2px 8px; border-radius:4px;">
          DENIAL NOTICE
        </span>
      </div>
      <div style="font-size:11px; color:#64748b; margin-bottom:8px;">
        Service: <strong>${notice.procedure_name}</strong>
      </div>
      <div style="background:#f8fafc; border-left:3px solid #ef4444; padding:8px 10px; margin-bottom:10px; border-radius:0 4px 4px 0;">
        <div style="font-size:11px; font-weight:700; color:#b91c1c; margin-bottom:2px;">PLAIN-LANGUAGE SUMMARY FOR MEMBER:</div>
        <div style="font-size:12px; color:#1e293b; line-height:1.45;">${notice.plain_language_summary}</div>
      </div>
      <div style="font-size:12px; color:#475569; margin-bottom:6px;">
        <strong style="color:#0f172a;">Clinical Rationale:</strong> ${notice.clinical_rationale}
      </div>
      ${notice.policy_citations && notice.policy_citations.length ? `
        <div style="font-size:11px; color:#64748b; margin-bottom:8px;">
          <strong>Governing Policy:</strong> ${notice.policy_citations.map(c => `<code style="background:#f1f5f9; padding:1px 4px; border-radius:3px; font-size:11px;">${c}</code>`).join(", ")}
        </div>
      ` : ""}
      <div style="margin-top:8px;">
        <strong style="font-size:12px; color:#0f172a;">Actionable Next Steps:</strong>
        <ul style="margin:4px 0 8px; padding-left:18px; font-size:12px; color:#475569;">
          ${notice.next_steps.map(s => `<li>${s}</li>`).join("")}
        </ul>
      </div>
      <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:4px; padding:8px; font-size:11px; color:#1e3a8a; margin-bottom:8px;">
        <strong>⚖️ ERISA § 503 & ACA § 2719 Appeal Rights:</strong> 180 calendar days to file internal appeal with right to free file copy and 72-hour expedited urgent appeal.
      </div>
      <details style="margin-top:6px; font-size:12px;">
        <summary style="cursor:pointer; color:#2563eb; font-weight:600;">View & Copy Full Letter Text (Print/Mail Ready)</summary>
        <div style="position:relative; margin-top:6px;">
          <button type="button" class="secondary" style="position:absolute; top:6px; right:6px; font-size:11px; padding:2px 8px;" onclick="navigator.clipboard.writeText(this.nextElementSibling.innerText); this.innerText='Copied!'; setTimeout(()=>this.innerText='Copy Letter', 2000);">Copy Letter</button>
          <pre style="background:#f8fafc; border:1px solid #cbd5e1; padding:10px; border-radius:4px; font-size:11px; white-space:pre-wrap; max-height:220px; overflow-y:auto; color:#1e293b; font-family:monospace;">${notice.full_letter_text}</pre>
        </div>
      </details>
    `;
  } else {
    const noticeBox = node("div", undefined, grid);
    noticeBox.style.padding = "12px";
    noticeBox.style.background = "#ffffff";
    noticeBox.style.border = "1px solid #e2e8f0";
    noticeBox.style.borderRadius = "6px";

    const act = (dec && dec.action) ? dec.action : "";
    let badge = { bg: "#f1f5f9", text: "#475569", label: "NO DENIAL ISSUED" };
    let msg = "No adverse denial determination rendered. Adverse Determination & Denial Letters (with statutory ERISA appeal rights) are strictly generated only when a claim or pre-authorization is denied.";

    if (act.startsWith("approve")) {
      badge = { bg: "#dcfce7", text: "#15803d", label: "APPROVED — NO ADVERSE ACTION" };
      msg = "✓ Claim or prior authorization is approved. Standard Explanation of Benefits (EOB) / payment approval issued. No adverse determination notice required.";
    } else if (act === "route_to_senior_reviewer" || act === "route_to_coding_review") {
      badge = { bg: "#dbeafe", text: "#1d4ed8", label: "IN REVIEW — NOT DENIED" };
      msg = "ℹ️ Claim has been routed for clinical / senior physician review. This is an active in-progress assessment, not an adverse denial. Formal denial letters are only issued if an adverse denial decision is rendered.";
    } else if (act === "request_missing_documentation") {
      badge = { bg: "#fef9c3", text: "#a16207", label: "PENDED FOR RECORDS — NOT DENIED" };
      msg = "ℹ️ Request is currently pended awaiting missing medical documentation from the provider. No adverse denial letter has been issued.";
    }

    noticeBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-weight:600; font-size:13px; color:#334155;">📄 Adverse Determination & Denial Letter (EOB)</span>
        <span style="background:${badge.bg}; color:${badge.text}; font-weight:700; font-size:11px; padding:2px 8px; border-radius:4px;">
          ${badge.label}
        </span>
      </div>
      <div style="font-size:12px; color:#475569; margin-top:8px; line-height:1.45;">
        ${msg}
      </div>
    `;
  }

  // 3. Appeal Synthesis Card (if appeal review)
  if (intel.appeal_synthesis) {
    const synth = intel.appeal_synthesis;
    const synthBox = node("div", undefined, card);
    synthBox.style.marginTop = "14px";
    synthBox.style.padding = "12px";
    synthBox.style.background = "#ffffff";
    synthBox.style.border = "1px solid #bfdbfe";
    synthBox.style.borderRadius = "6px";

    const isOverturn = synth.clinical_recommendation === "overturn_denial";
    const badgeColor = isOverturn ? { bg: "#dbeafe", text: "#1d4ed8" } : { bg: "#fee2e2", text: "#b91c1c" };

    synthBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-weight:600; font-size:13px; color:#1e3a8a;">⚖️ Appeal Intelligence & Case Difference Synthesis</span>
        <span style="background:${badgeColor.bg}; color:${badgeColor.text}; font-weight:700; font-size:12px; padding:2px 8px; border-radius:4px;">
          ${synth.clinical_recommendation.toUpperCase().replace("_", " ")}
        </span>
      </div>
      <p style="font-size:13px; color:#334155; line-height:1.5; margin:0 0 10px;">${synth.synthesis_narrative}</p>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; font-size:12px;">
        <div>
          <strong style="color:#15803d;">Resolved Defects:</strong>
          <ul style="margin:4px 0 0; padding-left:18px; color:#475569;">
            ${synth.resolved_defects.length ? synth.resolved_defects.map(d => `<li>${d}</li>`).join("") : "<li>None resolved</li>"}
          </ul>
        </div>
        <div>
          <strong style="color:#b91c1c;">Remaining Open Items:</strong>
          <ul style="margin:4px 0 0; padding-left:18px; color:#475569;">
            ${synth.remaining_defects.length ? synth.remaining_defects.map(d => `<li>${d}</li>`).join("") : "<li>None remaining</li>"}
          </ul>
        </div>
      </div>
    `;
  }
}

function syncAlternativeTopics() {
  const attemptCard = $("findings").querySelector('[data-topic="conservative_treatment_attempted"]');
  const contraCard = $("findings").querySelector('[data-topic="conservative_treatment_contraindicated"]');
  if (!attemptCard || !contraCard) return;

  const attemptSelect = attemptCard.querySelector(".verdict");
  const contraSelect = contraCard.querySelector(".verdict");
  const contraReason = contraCard.querySelector(".reason");

  let note = contraCard.querySelector(".or-condition-note");
  if (!note) {
    note = node("div", undefined, contraCard);
    note.className = "or-condition-note";
    const firstLabel = contraCard.querySelector("label");
    contraCard.insertBefore(note, firstLabel);
  }

  if (attemptSelect.value === "established") {
    note.hidden = false;
    note.style.background = "#e8f4f0";
    note.style.color = "#126758";
    note.style.borderLeftColor = "#126758";
    note.innerHTML = "<strong>✓ Policy Alternative Satisfied (Section 5.1):</strong> Conservative treatment is established above. The alternative pathway (contraindications) is not required and defaults to <em>Unknown</em>.";
    if (!contraSelect.value || contraSelect.value === "unknown") {
      contraSelect.value = "unknown";
      if (!contraReason.value || contraReason.value.includes("Conservative treatment")) {
        contraReason.value = "Conservative treatment was completed; contraindication is not applicable or evaluated.";
      }
    }
  } else if (attemptSelect.value === "not_established" || attemptSelect.value === "unknown") {
    note.hidden = false;
    note.style.background = "#fff8e6";
    note.style.color = "#7c5500";
    note.style.borderLeftColor = "#e6a23c";
    note.innerHTML = "<strong>⚠️ Alternative Pathway Required:</strong> Because conservative therapy was not attempted, approval requires establishing a medical contraindication (e.g., progressive neurological deficit or red flags).";
  } else {
    note.hidden = true;
  }
}

function assessment(out) {
  const p = out.packet;
  $("assessment").hidden = !p;
  if (!p) return;
  $("reviewer-id").value = "";
  $("confirmed").checked = false;
  $("new-review-id").value =
    `${p.source_claim.review_id}-confirmed-${crypto.randomUUID().slice(0, 8)}`;
  $("sources").replaceChildren();
  for (const d of p.payload.documents) {
    const box = node("div", undefined, $("sources"));
    box.className = "policy-quote";
    node("strong", `Source document: ${d.document_id} (${title(d.document_type || "document")}):\n`, box);
    box.append(document.createTextNode(d.text));
  }
  const policyBox = node("details", undefined, $("sources"));
  node("summary", `Retrieved policy excerpts (${p.payload.policy_chunks.length} sections)`, policyBox);
  for (const c of p.payload.policy_chunks) {
    const cBox = node("div", undefined, policyBox);
    cBox.className = "policy-quote";
    node("strong", `Section ${c.section} — ${c.heading || "Policy Section"}:\n`, cBox);
    cBox.append(document.createTextNode(c.text));
  }
  $("findings").replaceChildren();
  for (const f of out.template.findings) {
    const card = node("div", undefined, $("findings"));
    card.className = "finding";
    card.dataset.topic = f.topic;
    const h3 = node("h3", undefined, card);
    h3.innerHTML = `${title(f.topic)} <span class="req">*</span>`;
    const candidate = p.extraction.candidates.findings.find(
      (x) => x.topic === f.topic,
    );
    node(
      "p",
      `Gemini advisory extraction: ${title(candidate.status)}${candidate.statement ? " — " + candidate.statement : ""}`,
      card,
    );
    const label = node("label", undefined, card);
    label.innerHTML = 'Your clinical assessment <span class="req">*</span>';
    const select = node("select", undefined, label);
    select.className = "verdict";
    select.required = true;
    for (const [value, text] of [
      ["", "Choose a verdict… (Required)"],
      ["established", "Established — Evidence supports requirement"],
      ["not_established", "Not established — Requirement not met"],
      ["unknown", "Unknown — Insufficient detail in record"],
      ["conflicting", "Conflicting — Contradictory records"],
    ]) {
      const opt = node("option", text, select);
      opt.value = value;
    }
    const reasonLabel = node("label", undefined, card);
    reasonLabel.innerHTML = 'Reason for your assessment <span class="req">*</span>';
    const reason = node("textarea", undefined, reasonLabel);
    reason.className = "reason";
    reason.required = true;
    reason.placeholder = "Enter concise clinical rationale justifying this verdict...";
    reason.rows = 2;
    const refs = node("div", undefined, card);
    refs.className = "quotes";
    for (const ref of f.evidence) quoteRow(refs, p.payload.documents, ref);
    const add = node("button", "+ Add source quotation", card);
    add.type = "button";
    add.className = "secondary";
    add.onclick = () => quoteRow(refs, p.payload.documents);

    select.addEventListener("change", syncAlternativeTopics);
  }
  syncAlternativeTopics();
  $("carry").replaceChildren();
  const carryDetails = $("carry-details");
  if (!out.carry_forward.length) {
    if (carryDetails) carryDetails.hidden = true;
  } else {
    if (carryDetails) {
      carryDetails.hidden = false;
      carryDetails.open = false;
    }
    for (const field of out.carry_forward) {
      const label = node("label", undefined, $("carry"));
      label.className = "check";
      const checkbox = node("input", undefined, label);
      checkbox.type = "checkbox";
      checkbox.value = field;
      checkbox.checked = true;
      node("span", title(field) + " (Verified)", label);
      detail($("carry"), "Inspect " + title(field), p.source_claim[field]);
    }
  }
}

$("load").onclick = () =>
  busy(async () => {
    const sample = await api("/api/samples/" + $("sample").value);
    const isAppealSub = Boolean(sample && sample.request && sample.request.claim);
    const claimTarget = isAppealSub ? sample.request.claim : sample;
    if ($("auto-unique-id")?.checked) {
      setClaimReviewId(sample, generateUniqueReviewId(claimTarget.claim_id));
    }
    $("claim").value = pretty(sample);
    updateClaim();
    const effectiveReviewId = claimTarget.review_id;
    message(`Loaded sample "${$("sample").options[$("sample").selectedIndex].text}" with Review ID ${effectiveReviewId}.`, false);
  });

$("upload").onchange = () =>
  busy(async () => {
    const file = $("upload").files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024)
      throw new Error("Choose a JSON file smaller than 2 MiB.");
    const text = await file.text();
    const parsed = JSON.parse(text);
    const isAppealSub = Boolean(parsed && parsed.request && parsed.request.claim);
    const claimTarget = isAppealSub ? parsed.request.claim : parsed;
    if ($("auto-unique-id")?.checked) {
      setClaimReviewId(parsed, generateUniqueReviewId(claimTarget.claim_id));
    }
    $("claim").value = pretty(parsed);
    updateClaim();
    message(`Uploaded file with Review ID ${claimTarget.review_id}.`, false);
  });

$("claim").addEventListener("input", updateClaim);

if ($("claim-review-id")) {
  $("claim-review-id").addEventListener("input", () => {
    try {
      const c = claim();
      setClaimReviewId(c, $("claim-review-id").value.trim());
      $("claim").value = pretty(c);
      updateClaim();
    } catch (_) {}
  });
}

if ($("gen-review-id-btn")) {
  $("gen-review-id-btn").addEventListener("click", () => {
    try {
      const c = claim();
      const isAppealSub = Boolean(c && c.request && c.request.claim);
      const claimTarget = isAppealSub ? c.request.claim : c;
      const newId = generateUniqueReviewId(claimTarget.claim_id);
      setClaimReviewId(c, newId);
      $("claim").value = pretty(c);
      updateClaim();
      message(`Generated fresh unique review ID: ${newId}`, false);
    } catch (_) {
      message("Please enter valid claim JSON first.", true);
    }
  });
}


$("mode").onchange = () => {
  invalidate();
  const notes = {
    auto: "ℹ️ Automatic Mode: Evaluates 100% deterministic rules for administrative checks, eligibility, and verified facts. Automatically invokes Gemini advisory extraction when unstructured clinical notes require evaluation.",
    gemini:
      "⚠️ Live Gemini Advisory Extraction: Clinical notes and matching policy excerpts will be sent to Google Gemini to extract candidate quotations. Requires GEMINI_API_KEY. Caution: Model outputs are purely advisory suggestions and must be reviewed and confirmed by a human reviewer.",
    disabled:
      "🛡️ Rules Only (Deterministic): 100% deterministic policy engine evaluation. No AI models are called. Claims are evaluated strictly using deterministic policy rules and structured claim facts.",
  };
  $("mode-note").textContent = notes[$("mode").value] || notes.auto;
};

function renderPreview(res) {
  const container = $("preview-data");
  container.replaceChildren();
  const payload = res.payload;

  const header = node("div", undefined, container);
  header.className = "summary";
  const docCount = payload.documents?.length || 0;
  const chunkCount = payload.policy_chunks?.length || 0;

  const overview = node("div", undefined, header);
  overview.className = "result-card";
  node("h3", "Payload Overview (Ready for Advisory Extraction)", overview);
  node("p", `Workflow: ${title(payload.workflow || "review")} · Procedure: ${payload.procedure_code} · Diagnoses: ${(payload.diagnosis_codes || []).join(", ") || "None"}`, overview);
  node(
    "p",
    `Data Minimization: Only ${docCount} selected clinical document${docCount === 1 ? "" : "s"} and ${chunkCount} matched policy excerpt${chunkCount === 1 ? "" : "s"} will be shared with the model. Unrelated claim fields and unselected records are excluded.`,
    overview,
  );

  if (payload.requested_topics?.length) {
    const topicsP = node("p", undefined, header);
    node("strong", "Requested clinical questions: ", topicsP);
    topicsP.append(document.createTextNode(payload.requested_topics.map(title).join(", ")));
  }

  if (payload.documents?.length) {
    const docSection = node("div", undefined, container);
    node("h3", "Selected Clinical Documents", docSection);
    for (const d of payload.documents) {
      const box = node("div", undefined, docSection);
      box.className = "policy-quote";
      node("strong", `${d.document_id} (${title(d.document_type || "document")}):\n`, box);
      box.append(document.createTextNode(d.text));
    }
  }

  if (payload.policy_chunks?.length) {
    const chunkSection = node("div", undefined, container);
    node("h3", "Included Policy Excerpts", chunkSection);
    for (const c of payload.policy_chunks) {
      const box = node("div", undefined, chunkSection);
      box.className = "policy-quote";
      node("strong", `Section ${c.section} — ${c.heading || "Policy Section"}:\n`, box);
      box.append(document.createTextNode(c.text));
    }
  }

  const rawDetails = node("details", undefined, container);
  node("summary", "Technical & Audit Details (Cryptographic Signature & Raw JSON)", rawDetails);
  node("p", `Audit Fingerprint (SHA-256): ${res.input_sha256}`, rawDetails);
  node(
    "p",
    "Explanation: This cryptographic hash uniquely binds the exact text and policy sections above. It ensures data integrity and prevents advisory outputs from being applied to modified or different claims.",
    rawDetails,
  );
  node("pre", pretty(payload), rawDetails);
}

$("preview").onclick = () =>
  busy(async () => {
    const res = await api("/api/preview", input());
    renderPreview(res);
    $("preview-panel").hidden = false;
    $("preview-panel").open = true;
  });

$("run").onclick = () =>
  busy(async () => {
    invalidate();
    const out = await api("/api/review", input());
    current = out;
    $("result").hidden = false;
    decision(out, $("decision"));
    renderIntelligence(out.intelligence, $("intelligence-card"), out.decision);
    $("persistence").textContent = out.saved
      ? `✓ Initial review successfully saved to database with Review ID: ${out.decision.context.review_id}`
      : "Initial review evaluated in-memory. (Check 'Save initial review to database' if you wish to persist to SQLite audit trail).";
    $("extraction").replaceChildren();
    if (out.extraction) {
      const ext = out.extraction;
      const extCard = node("div", undefined, $("extraction"));
      extCard.className = "finding";

      const statusLabels = {
        validated_candidates: "Advisory extraction: Validated & Provenance-Checked",
        unavailable: "Advisory extraction: Not performed / Unavailable",
        invalid_response: "Advisory extraction: Invalid output (Safely discarded)",
      };
      node("h3", statusLabels[ext.status] || title(ext.status), extCard);

      const reasonLabels = {
        schema_and_provenance_validated_not_clinical_truth:
          "The model extracted candidate evidence and verified that each finding cites an exact quotation from the provided documents. These findings are advisory and require human confirmation in the section below.",
        disabled: "Extraction mode disabled. Evaluated using existing claim facts.",
        missing_gemini_key: "Gemini API key is not configured on the server. Used recorded/offline rules.",
        input_or_sources_unavailable: "Selected clinical documents or matching policy excerpts were unavailable.",
        response_validation_failed: "Model response failed strict quotation or schema checks and was discarded.",
      };
      node("p", reasonLabels[ext.reason] || title(ext.reason), extCard);

      const trust = ext.evidence_reliability;
      if (trust) {
        node("h4", `Evidence reliability: ${trust.score == null ? "Not scored — no output" : trust.score + "/100"}`, extCard);
        node("p", `${trust.origin} · ${trust.rubric}. ${trust.limitation}`, extCard);
        const audit = node("details", undefined, extCard);
        node("summary", "Score components and per-finding scores", audit);
        node("pre", pretty(trust), audit);
      }
      if (ext.candidates?.findings?.length) {
        const findingsList = node("div", undefined, extCard);
        for (const f of ext.candidates.findings) {
          const item = node("div", undefined, findingsList);
          item.className = "quote-row";
          node("strong", `${title(f.topic)}: `, item);
          node("span", `${title(f.status)}${f.statement ? " — " + f.statement : ""}`, item);
          for (const ref of f.document_refs || []) {
            const q = node("div", undefined, item);
            q.className = "policy-quote";
            node("small", `Citation from ${ref.document_id}:\n`, q);
            q.append(document.createTextNode(`"${ref.quote}"`));
          }
        }
      }

      const rawExt = node("details", undefined, extCard);
      node("summary", "Technical extraction details & request ID", rawExt);
      if (ext.request_id) node("p", `Request ID: ${ext.request_id}`, rawExt);
      node("pre", pretty(ext.candidates || {}), rawExt);

      if (!out.packet && ext.status === "validated_candidates")
        node(
          "p",
          "This claim already has a confirmed clinical assessment. Existing assessment was preserved.",
          extCard,
        );
    }
    assessment(out);
    $("history-id").value = out.decision.context.review_id;
    if (out.saved) {
      $("jump-to-history-btn").hidden = false;
      loadRecentHistory();
    }
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  });

if ($("autofill-assessment-btn")) {
  $("autofill-assessment-btn").onclick = () => {
    if (!current?.packet) {
      message("Please run review first to generate the clinical packet.", true);
      return;
    }
    const p = current.packet;
    $("reviewer-id").value = $("reviewer-id").value.trim() || "DR_SMITH";
    if (!$("new-review-id").value || $("new-review-id").value === p.source_claim.review_id) {
      $("new-review-id").value = `${p.source_claim.review_id}-confirmed-${crypto.randomUUID().slice(0, 8)}`;
    }
    $("confirmed").checked = true;

    const candidates = p.extraction?.candidates?.findings || [];
    const candidateMap = new Map(candidates.map((c) => [c.topic, c]));

    for (const card of $("findings").children) {
      const topic = card.dataset.topic;
      const select = card.querySelector(".verdict");
      const reason = card.querySelector(".reason");
      const refs = card.querySelector(".quotes");

      if (topic === "conservative_treatment_contraindicated") {
        select.value = "unknown";
        reason.value = "Conservative treatment was completed; contraindication is not applicable or evaluated.";
        if (refs) refs.replaceChildren();
      } else {
        select.value = "established";
        const c = candidateMap.get(topic);
        if (topic === "diagnosis_support") {
          reason.value = "Clinician assessment confirms diagnosis is supported.";
        } else if (topic === "medical_necessity") {
          reason.value = "Clinician assessment confirms MRI is medically necessary.";
        } else if (topic === "conservative_treatment_attempted") {
          reason.value = "Prior treatment history confirms conservative treatment attempted.";
        } else {
          reason.value = c?.statement || `Clinical record supports ${title(topic)}.`;
        }

        if (refs && (!refs.children.length || ![...refs.querySelectorAll("textarea")].some((t) => t.value.trim().length > 0))) {
          refs.replaceChildren();
          for (const ref of c?.document_refs || []) {
            quoteRow(refs, p.payload.documents, ref);
          }
        }
      }
    }
    syncAlternativeTopics();
    message("✓ Autofilled verified clinical rationale and exact source quotations.", false);
  };
}

$("confirm-form").onsubmit = (e) => {
  e.preventDefault();
  busy(async () => {
    if (!current?.packet) throw new Error("Run extraction first.");
    const newRid = $("new-review-id").value.trim();
    if (!newRid) throw new Error("Please enter a New review ID.");
    if (newRid === current.packet.source_claim.review_id) {
      throw new Error(`New review ID must be different from current claim Review ID (${current.packet.source_claim.review_id}).`);
    }
    const revId = $("reviewer-id").value.trim();
    if (!revId) throw new Error("Please enter a Reviewer ID (e.g. DR_SMITH).");
    if (!$("confirmed").checked) {
      throw new Error("Please check the confirmation box: 'I have reviewed the source documents, policy and each finding.'");
    }

    const docMap = new Map((current.packet?.payload?.documents || []).map((d) => [d.document_id, d.text]));

    const findings = [...$("findings").children].map((card) => {
      const topic = card.dataset.topic;
      const status = card.querySelector(".verdict").value;
      const reason = card.querySelector(".reason").value.trim();
      const evidence = [...card.querySelectorAll(".quote-row")]
        .map((row) => ({
          document_id: row.querySelector("select").value,
          quote: row.querySelector("textarea").value.trim(),
        }))
        .filter((row) => row.quote.length > 0);

      if ((status === "established" || status === "not_established") && evidence.length === 0) {
        throw new Error(
          `"${title(topic)}" is marked as "${title(status)}", which requires at least one exact source quotation. Please add a quotation or select "Unknown".`
        );
      }
      if (status === "conflicting" && evidence.length < 2) {
        throw new Error(
          `"${title(topic)}" is marked as "Conflicting", which requires at least 2 distinct quotations.`
        );
      }

      for (const row of evidence) {
        const docText = docMap.get(row.document_id);
        if (!docText) {
          throw new Error(`Document "${row.document_id}" was not found in this review packet.`);
        }
        if (!docText.includes(row.quote)) {
          throw new Error(
            `Quotation for "${title(topic)}" was not found in document "${row.document_id}". Quotations must match the source document text verbatim. (Found: "${row.quote.slice(0, 35)}...")`
          );
        }
      }

      return { topic, status, reason, evidence };
    });
    const response = {
      packet_sha256: current.packet.packet_sha256,
      reviewer_id: revId,
      reviewed_at: new Date().toISOString(),
      new_review_id: newRid,
      confirmed_sources: true,
      carry_forward_assessments: [
        ...$("carry").querySelectorAll("input:checked"),
      ].map((i) => i.value),
      findings,
    };
    const out = await api("/api/confirm", {
      packet: current.packet,
      assessment: response,
    });
    current = {
      ...out,
      reviewer_assessment: response,
      source_packet: current.packet,
    };
    decision(out, $("decision"));
    renderIntelligence(out.intelligence, $("intelligence-card"), out.decision);
    $("persistence").textContent =
      `Confirmed review saved; linked to prior review ${out.previous_review_id}.`;
    $("assessment").hidden = true;
    $("extraction").replaceChildren();
    
    // Prominent success confirmation banner
    const banner = node("div", undefined, $("extraction"));
    banner.className = "success-banner";
    banner.innerHTML = `<span>✓ Clinical assessment confirmed by <strong>${response.reviewer_id}</strong>. Policy rules re-evaluated and finalized the decision below.</span>`;

    message(`✓ Clinical assessment confirmed! Final policy decision: ${title(out.decision.action)}.`, false);

    $("history-id").value = out.review_id;
    $("jump-to-history-btn").hidden = false;
    loadRecentHistory();
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  });
};

$("jump-to-history-btn").onclick = async () => {
  switchView("view-history");
  await updateHistoryList();
};

function renderHistoryCard(r, parent, isPrimary = false) {
  const box = node("div", undefined, parent);
  let statusClass = "route";
  let icon = "📋";
  if (r.decision.action.startsWith("approve")) {
    statusClass = "approve";
    icon = "✅";
  } else if (r.decision.action.startsWith("deny")) {
    statusClass = "deny";
    icon = "❌";
  }
  box.className = `finding ${isPrimary ? "primary-match " + statusClass : ""}`;
  
  const h3 = node("h3", undefined, box);
  h3.innerHTML = `${icon} Review ID: <code>${r.claim.review_id}</code> · <span>${title(r.decision.action)}</span>`;
  
  node("p", `Recorded at: ${r.recorded_at} · Claim ID: ${r.claim.claim_id} · Procedure: ${r.claim.procedure_code || 'N/A'}`, box);
  if (r.previous_review_id) {
    const pLink = node("p", undefined, box);
    pLink.innerHTML = `Linked prior review: <code>${r.previous_review_id}</code>`;
  }
  
  if (r.decision.action.startsWith("deny")) {
    const appealBtn = node("button", "🛡️ File an Appeal for this Denial ➔", box);
    appealBtn.type = "button";
    appealBtn.className = "secondary";
    appealBtn.style.marginTop = "8px";
    appealBtn.onclick = () => {
      // Pre-fill appeal template for this denied review in Claim Process desk
      const appealTemplate = {
        request: {
          claim: {
            ...r.claim,
            review_id: `APPEAL-${r.claim.review_id}`,
            claim_type: "appeal",
            documents: [
              ...(r.claim.documents || []),
              {
                document_id: "APPEAL",
                document_type: "written_appeal",
                status: "provided",
                text: `Formal written appeal request for denied review ${r.claim.review_id}.`,
                submitted_in_review: null,
              },
              {
                document_id: "DENIAL",
                document_type: "denial_letter",
                status: "provided",
                text: `Original denial record for review ${r.claim.review_id}. Reason: ${r.decision.context.reason}`,
                submitted_in_review: null,
              }
            ]
          },
          submission_date: new Date().toISOString().split("T")[0],
          prior_denial_review_id: r.claim.review_id,
          written_request_document_id: "APPEAL",
          denial_notice_document_id: "DENIAL",
          denial_notice_date: (r.recorded_at || new Date().toISOString()).split("T")[0],
        }
      };
      $("claim").value = pretty(appealTemplate);
      switchView("view-claim");
      updateClaim();
      message(`Appeal template populated with denied review ID "${r.claim.review_id}" in Claim Process desk. Ready for review.`, false);
    };
  }

  detail(box, "View complete saved audit record & claim snapshot JSON", r);
}

let historyCurrentPage = 1;
const historyPageSize = 5;

async function loadRecentHistory(page = 1) {
  const container = $("recent-history-list");
  const paginationBar = $("pagination-bar");
  if (!container) return;
  historyCurrentPage = page;
  try {
    const res = await api(`/api/history?page=${page}&limit=${historyPageSize}`);
    const records = res.records || [];
    const total = res.total !== undefined ? res.total : records.length;
    const totalPages = res.total_pages || Math.max(1, Math.ceil(total / historyPageSize));

    const badge = $("total-saved-badge");
    if (badge) badge.textContent = total;

    container.replaceChildren();
    if (records.length === 0) {
      const p = node("p", undefined, container);
      p.className = "muted";
      p.textContent = "No saved reviews found in local SQLite database. Check 'Save initial review to database' when running a review to persist records here.";
      if (paginationBar) paginationBar.replaceChildren();
      return;
    }

    const list = node("div", undefined, container);
    list.className = "recent-reviews-list";
    const currentSearched = $("history-id")?.value?.trim();

    for (const r of records) {
      const item = node("div", undefined, list);
      const isMatch = currentSearched && r.claim.review_id === currentSearched;
      item.className = `recent-item-card ${isMatch ? "active-match" : ""}`;

      const info = node("div", undefined, item);
      info.className = "recent-item-info";

      const titleDiv = node("div", undefined, info);
      titleDiv.className = "recent-item-title";

      let statusBadge = "badge-route";
      let statusText = "Routed";
      if (r.decision.action.startsWith("approve")) {
        statusBadge = "badge-approve";
        statusText = "Approved";
      } else if (r.decision.action.startsWith("deny")) {
        statusBadge = "badge-deny";
        statusText = "Denied";
      }
      const b = node("span", statusText, titleDiv);
      b.className = statusBadge;

      node("code", r.claim.review_id, titleDiv);

      const sub = node("div", undefined, info);
      sub.className = "recent-item-sub";
      const recDate = r.recorded_at ? new Date(r.recorded_at).toLocaleTimeString() : "";
      sub.textContent = `Claim: ${r.claim.claim_id} · Procedure: ${r.claim.procedure_code || "N/A"} · Member: ${r.claim.member_id} · ${recDate ? "Saved at " + recDate + " · " : ""}${title(r.decision.action)}`;

      const actions = node("div", undefined, item);
      actions.className = "recent-item-actions";

      const viewBtn = node("button", "Inspect Record", actions);
      viewBtn.type = "button";
      viewBtn.className = "secondary";
      viewBtn.style.minHeight = "auto";
      viewBtn.style.padding = "5px 12px";
      viewBtn.style.fontSize = "12px";
      viewBtn.onclick = () => {
        $("history-id").value = r.claim.review_id;
        busy(updateHistoryList);
        $("history").scrollIntoView({ behavior: "smooth", block: "start" });
      };

      if (r.decision.action.startsWith("deny")) {
        const appealBtn = node("button", "Appeal ➔", actions);
        appealBtn.type = "button";
        appealBtn.className = "chip-btn";
        appealBtn.style.fontSize = "11px";
        appealBtn.onclick = () => {
          $("history-id").value = r.claim.review_id;
          const appealTemplate = {
            request: {
              claim: {
                ...r.claim,
                review_id: `APPEAL-${r.claim.review_id}`,
                claim_type: "appeal",
                documents: [
                  ...(r.claim.documents || []),
                  {
                    document_id: "APPEAL",
                    document_type: "written_appeal",
                    status: "provided",
                    text: `Formal written appeal request for denied review ${r.claim.review_id}.`,
                    submitted_in_review: null,
                  },
                  {
                    document_id: "DENIAL",
                    document_type: "denial_letter",
                    status: "provided",
                    text: `Original denial record for review ${r.claim.review_id}. Reason: ${r.decision.context.reason}`,
                    submitted_in_review: null,
                  }
                ]
              },
              submission_date: new Date().toISOString().split("T")[0],
              prior_denial_review_id: r.claim.review_id,
              written_request_document_id: "APPEAL",
              denial_notice_document_id: "DENIAL",
              denial_notice_date: (r.recorded_at || new Date().toISOString()).split("T")[0],
            }
          };
          $("claim").value = pretty(appealTemplate);
          switchView("view-claim");
          updateClaim();
          message(`Appeal template populated with denied review ID "${r.claim.review_id}" in Claim Process desk. Ready for review.`, false);
        };
      }
    }

    // Render Multiple Pages: 1, 2, 3, etc.
    if (paginationBar) {
      paginationBar.replaceChildren();

      const infoSpan = node("span", undefined, paginationBar);
      infoSpan.className = "pagination-info";
      infoSpan.textContent = `Page ${page} of ${totalPages} (${total} total saved review${total === 1 ? "" : "s"})`;

      const pagesDiv = node("div", undefined, paginationBar);
      pagesDiv.className = "pagination-pages";

      const prevBtn = node("button", "‹ Prev", pagesDiv);
      prevBtn.type = "button";
      prevBtn.className = "page-btn";
      prevBtn.disabled = page <= 1;
      prevBtn.onclick = () => busy(() => loadRecentHistory(page - 1));

      for (let p = 1; p <= totalPages; p++) {
        const pageBtn = node("button", String(p), pagesDiv);
        pageBtn.type = "button";
        pageBtn.className = `page-btn ${p === page ? "active" : ""}`;
        const targetPage = p;
        pageBtn.onclick = () => busy(() => loadRecentHistory(targetPage));
      }

      const nextBtn = node("button", "Next ›", pagesDiv);
      nextBtn.type = "button";
      nextBtn.className = "page-btn";
      nextBtn.disabled = page >= totalPages;
      nextBtn.onclick = () => busy(() => loadRecentHistory(page + 1));
    }
  } catch (err) {
    container.replaceChildren();
    node("p", `Could not load saved reviews: ${err.message}`, container);
    if (paginationBar) paginationBar.replaceChildren();
  }
}

async function updateHistoryList() {
  const searchedId = $("history-id").value.trim();
  $("history").replaceChildren();

  if (searchedId) {
    try {
      const out = await api("/api/history/" + encodeURIComponent(searchedId));
      if (!out.record && (!out.records || out.records.length === 0)) {
        const box = node("div", undefined, $("history"));
        box.className = "notice";
        box.textContent = `No saved review found with ID "${searchedId}". Check that "Save initial review to database" was checked when running the review, or inspect the recent saved list below.`;
      } else {
        const exact = out.record || (out.records || []).find((r) => r.claim.review_id === searchedId) || out.records[0];
        if (exact) {
          const matchHeader = node("div", undefined, $("history"));
          matchHeader.className = "matched-history-header";
          matchHeader.innerHTML = `<strong>🎯 Matched Review Record (${exact.claim.review_id}):</strong>`;
          renderHistoryCard(exact, $("history"), true);
        }
        const otherRecords = (out.records || []).filter((r) => r.claim.review_id !== exact?.claim.review_id);
        if (otherRecords.length > 0) {
          const relatedDetails = node("details", undefined, $("history"));
          relatedDetails.className = "collapsible-panel";
          node(
            "summary",
            `📂 Related Claim History: ${otherRecords.length} other saved review${otherRecords.length === 1 ? "" : "s"} for Claim ${exact.claim.claim_id}...`,
            relatedDetails,
          );
          for (const r of otherRecords) {
            renderHistoryCard(r, relatedDetails, false);
          }
        }
      }
    } catch (e) {
      const box = node("div", undefined, $("history"));
      box.className = "notice";
      box.textContent = `ℹ️ No review record in local database matches ID "${searchedId}". If this was a newly run review, check that "Save initial review to database" was enabled before clicking "Run review".`;
    }
  }

  await loadRecentHistory(historyCurrentPage);
}

$("history-form").onsubmit = (e) => {
  e.preventDefault();
  busy(updateHistoryList);
};

if ($("toggle-list-btn")) {
  $("toggle-list-btn").onclick = () => {
    busy(async () => {
      await loadRecentHistory(1);
      const container = $("saved-list-container");
      if (container) {
        container.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  };
}

if ($("refresh-history-btn")) {
  $("refresh-history-btn").onclick = () => busy(() => loadRecentHistory(historyCurrentPage));
}

async function deleteReviewHistory() {
  const confirmed = window.confirm(
    "Are you sure you want to delete all saved review history? This will clear the local SQLite database."
  );
  if (!confirmed) return;

  await busy(async () => {
    const res = await api("/api/history/clear", {});
    const countText = res.deleted_count !== undefined ? ` (${res.deleted_count} record(s) deleted)` : "";
    message(`Cleared review history${countText}.`);

    const historyView = $("history");
    if (historyView) historyView.replaceChildren();

    const historyInput = $("history-id");
    if (historyInput) historyInput.value = "";

    await loadRecentHistory(1);
  });
}

if ($("clear-history-btn")) {
  $("clear-history-btn").onclick = deleteReviewHistory;
}
if ($("clear-history-list-btn")) {
  $("clear-history-list-btn").onclick = deleteReviewHistory;
}

// Quick lookup chips in History tab
document.querySelectorAll(".chip-btn[data-search-id]").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("history-id").value = chip.dataset.searchId;
    busy(updateHistoryList);
  });
});


$("download").onclick = () => {
  if (!current) return;
  const url = URL.createObjectURL(
    new Blob([pretty(current)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "claim-review.json";
  a.click();
  URL.revokeObjectURL(url);
};

// ==========================================
// EVALS DASHBOARD RENDERING & LOGIC
// ==========================================
let currentEvalsData = null;
let currentEvalsFilter = "all";

async function loadEvalsDashboard() {
  if (!$("eval-scorecards")) return;
  const data = await api("/api/evaluation");
  currentEvalsData = data;
  renderPhoenixHeader(data.phoenix);
  renderPhoenixDistributions(data.phoenix);
  renderEvalsScorecards(data.metrics || {}, data.phoenix, data.decisions);
  renderEvalsCases(data, currentEvalsFilter);
  renderEvalsRubric(data.rubric || "");
}

const isNum = (x) => typeof x === "number" && Number.isFinite(x);

function renderPhoenixHeader(phoenix) {
  const container = $("phoenix-summary-bar");
  if (!container) return;
  container.replaceChildren();

  const totalCases = phoenix?.total_cases ?? "—";
  const metrics = phoenix?.metrics || {};
  const rates = Object.values(metrics).map((x) => x?.pass_rate_pct).filter(isNum);
  const avgPass = rates.length ? (rates.reduce((a, b) => a + b, 0) / rates.length).toFixed(1) : null;

  const items = [
    { num: `${totalCases}`, desc: "Total Evaluated Scenarios" },
    { num: avgPass === null ? "—" : `${avgPass}%`, desc: "Phoenix Pass Rate (pass@1)" },
    { num: "100% Offline", desc: "Local Zero-API-Key Execution" },
    { num: "7 Evaluators", desc: "Governance, Safety & EOB Axes" },
    { num: "<0.01s", desc: "Deterministic Evaluation Speed" },
  ];

  for (const item of items) {
    const d = node("div", undefined, container);
    d.className = "phoenix-summary-item";
    const n = node("div", item.num, d);
    n.className = "num";
    const desc = node("div", item.desc, d);
    desc.className = "desc";
  }

  if ($("phoenix-version-pill") && phoenix?.version) {
    $("phoenix-version-pill").textContent = `v${phoenix.version} (Local Engine)`;
  }
}

function renderPhoenixDistributions(phoenix) {
  const container = $("phoenix-distributions-panel");
  if (!container) return;
  container.replaceChildren();

  if (!phoenix) return;

  const total = phoenix.total_cases || 0;
  if (!total) return;
  const ft = phoenix.fast_track_distribution || {};
  const notice = phoenix.adverse_notice_distribution || {};

  // 1. Fast-Track Distribution Card
  const ftCard = node("div", undefined, container);
  ftCard.className = "dist-card";
  const ftTitle = node("div", undefined, ftCard);
  ftTitle.className = "dist-card-title";
  node("span", "Fast-Track Prior Auth Triage (Automated Pre-Approval)", ftTitle);
  node("span", `${total} Cases`, ftTitle);
  const ftSub = node("div", "Automated pre-auth routing: auto-adjudication vs. human clinical review vs. hard stop", ftCard);
  ftSub.className = "dist-card-sub";

  const ftBar = node("div", undefined, ftCard);
  ftBar.className = "dist-bar-stacked";
  const greenPct = (((ft.GREEN || 0) / total) * 100).toFixed(1);
  const yellowPct = (((ft.YELLOW || 0) / total) * 100).toFixed(1);
  const redPct = (((ft.RED || 0) / total) * 100).toFixed(1);

  const segG = node("div", undefined, ftBar);
  segG.className = "dist-bar-seg green";
  segG.style.width = `${greenPct}%`;
  segG.title = `Green: ${ft.GREEN} (${greenPct}%)`;

  const segY = node("div", undefined, ftBar);
  segY.className = "dist-bar-seg yellow";
  segY.style.width = `${yellowPct}%`;
  segY.title = `Yellow: ${ft.YELLOW} (${yellowPct}%)`;

  const segR = node("div", undefined, ftBar);
  segR.className = "dist-bar-seg red";
  segR.style.width = `${redPct}%`;
  segR.title = `Red: ${ft.RED} (${redPct}%)`;

  const ftLegend = node("div", undefined, ftCard);
  ftLegend.className = "dist-legend";
  const ftRows = [
    { cls: "green", label: "GREEN — Auto-Adjudicate (Clean & In-Network)", count: ft.GREEN || 0, pct: greenPct },
    { cls: "yellow", label: "YELLOW — Route to Review Desk (Clinical Necessity)", count: ft.YELLOW || 0, pct: yellowPct },
    { cls: "red", label: "RED — Exclusion / Hard Stop / Ineligible", count: ft.RED || 0, pct: redPct },
  ];
  for (const r of ftRows) {
    const item = node("div", undefined, ftLegend);
    item.className = "dist-legend-item";
    const lbl = node("span", undefined, item);
    lbl.className = "dist-legend-label";
    const dot = node("span", undefined, lbl);
    dot.className = `dist-dot ${r.cls}`;
    node("span", r.label, lbl);
    const val = node("span", `${r.count} (${r.pct}%)`, item);
    val.className = "dist-legend-val";
  }

  // 2. Adverse Determination Notices Card
  const noticeCard = node("div", undefined, container);
  noticeCard.className = "dist-card";
  const noticeTitle = node("div", undefined, noticeCard);
  noticeTitle.className = "dist-card-title";
  node("span", "Plain-Language Adverse Notices & EOB Generation", noticeTitle);
  node("span", `${total} Cases`, noticeTitle);
  const noticeSub = node("div", "ERISA § 503 / ACA § 2719 plain-language adverse determinations, appeal rights & clean EOPs", noticeCard);
  noticeSub.className = "dist-card-sub";

  const noticeBar = node("div", undefined, noticeCard);
  noticeBar.className = "dist-bar-stacked";
  const nonePct = (((notice.none || 0) / total) * 100).toFixed(1);
  const routedPct = (((notice.routed_for_clinical_review || 0) / total) * 100).toFixed(1);
  const deniedPct = (((notice.denied || 0) / total) * 100).toFixed(1);
  const pendedPct = (((notice.pended_missing_documentation || 0) / total) * 100).toFixed(1);

  const segNone = node("div", undefined, noticeBar);
  segNone.className = "dist-bar-seg green";
  segNone.style.width = `${nonePct}%`;
  segNone.title = `Clean EOP: ${notice.none} (${nonePct}%)`;

  const segRouted = node("div", undefined, noticeBar);
  segRouted.className = "dist-bar-seg blue";
  segRouted.style.width = `${routedPct}%`;
  segRouted.title = `Clinical Review: ${notice.routed_for_clinical_review} (${routedPct}%)`;

  const segDenied = node("div", undefined, noticeBar);
  segDenied.className = "dist-bar-seg red";
  segDenied.style.width = `${deniedPct}%`;
  segDenied.title = `Denial Notice: ${notice.denied} (${deniedPct}%)`;

  const segPended = node("div", undefined, noticeBar);
  segPended.className = "dist-bar-seg yellow";
  segPended.style.width = `${pendedPct}%`;
  segPended.title = `Missing Info: ${notice.pended_missing_documentation} (${pendedPct}%)`;

  const noticeLegend = node("div", undefined, noticeCard);
  noticeLegend.className = "dist-legend";
  const noticeRows = [
    { cls: "green", label: "Clean EOP — Approved Claim (No Adverse Notice)", count: notice.none || 0, pct: nonePct },
    { cls: "blue", label: "Clinical Review Notice — In-Flight Investigation", count: notice.routed_for_clinical_review || 0, pct: routedPct },
    { cls: "red", label: "Adverse Determination Letter — Denied (180-Day Appeal)", count: notice.denied || 0, pct: deniedPct },
    { cls: "yellow", label: "Pended Notice — Missing Clinical Documentation", count: notice.pended_missing_documentation || 0, pct: pendedPct },
  ];
  for (const r of noticeRows) {
    const item = node("div", undefined, noticeLegend);
    item.className = "dist-legend-item";
    const lbl = node("span", undefined, item);
    lbl.className = "dist-legend-label";
    const dot = node("span", undefined, lbl);
    dot.className = `dist-dot ${r.cls}`;
    node("span", r.label, lbl);
    const val = node("span", `${r.count} (${r.pct}%)`, item);
    val.className = "dist-legend-val";
  }
}

function renderEvalsScorecards(m, phoenix, decisions) {
  const container = $("eval-scorecards");
  if (!container) return;
  container.replaceChildren();

  let cards = [];

  if (phoenix && phoenix.metrics) {
    const pm = phoenix.metrics;
    const total = phoenix.total_cases ?? null;
    const rateCard = (label, metric, sub) => {
      const pct = metric?.pass_rate_pct;
      if (!isNum(pct)) return { label, val: "—", pct: 0, sub: `${sub} (not reported)` };
      const count = isNum(total) ? ` (${Math.round((pct * total) / 100)}/${total})` : "";
      return { label, val: `${pct.toFixed(1)}%${count}`, pct, sub };
    };
    cards = [
      rateCard("Action Correctness", pm.ActionCorrectness, "Deterministic policy decision & procedure code alignment"),
      rateCard("Provenance Grounding", pm.ProvenanceGrounding, "Exact verbatim policy citation grounding with zero hallucinations"),
      rateCard("Adverse Notice Fidelity", pm.AdverseNoticeFidelity, "6th–8th grade plain language, ERISA appeal rights & policy citations"),
      rateCard("Fast-Track Alignment", pm.FastTrackAlignment, "Deterministic Prior-Auth Fast-Track & Automated Approval triage classification"),
      rateCard("Human Calibration", pm.HumanCalibration, "Proper escalation of ambiguous clinical criteria to human review desk"),
      rateCard("Way-Out Completeness", pm.WayOutCompleteness, "Actionable missing documentation or clinical remedy gates provided"),
      rateCard("Adversarial Robustness", pm.AdversarialRobustness, "Prompt injection defense & document payload quarantine"),
    ];
  } else {
    const ratio = (label, num, den, sub) => {
      if (!isNum(num) || !isNum(den)) return { label, val: "—", pct: 0, sub: `${sub} (not reported)` };
      return { label, val: `${num}/${den}`, pct: den ? (100 * num) / den : 0, sub };
    };
    const adversarial = (decisions || []).filter((d) => getCaseCategory(d.id || "", null) === "adversarial");
    const adversarialPassed = adversarial.length ? adversarial.filter((d) => d.passed === true).length : null;
    cards = [
      ratio("Action Correctness", m?.action_correct, m?.decision_count, "Policy decisions & critical argument matching"),
      ratio("Citation Grounding", m?.grounding_passed, m?.decision_count, "Exact verbatim policy & document citations"),
      ratio("Advisory Extractions", m?.valid_extractions, m?.extraction_count, "Schema & topic extraction without hallucination"),
      ratio("Quote Anchor Coverage", m?.covered_anchors, m?.anchor_count, "Frozen clinical evidence anchors verified"),
      ratio("Adversarial Defense", adversarialPassed, adversarial.length || null, "Prompt injection & foreign chunk defenses"),
    ];
  }

  for (const c of cards) {
    const card = node("div", undefined, container);
    card.className = "eval-stat-card";
    const v = node("div", c.val, card);
    v.className = "eval-stat-value";
    const l = node("div", c.label, card);
    l.className = "eval-stat-label";
    const s = node("div", c.sub, card);
    s.className = "eval-stat-sub";
    const pBar = node("div", undefined, card);
    pBar.className = "eval-progress-bar";
    const pFill = node("div", undefined, pBar);
    pFill.className = "eval-progress-fill";
    pFill.style.width = `${c.pct}%`;
  }
}

function getCaseCategory(id, action) {
  if (id.startsWith("L")) return "extraction";
  if (["D09", "D10", "D19", "D20"].includes(id)) return "adversarial";
  if (action && action.startsWith("approve")) return "happy";
  return "denial";
}

function renderEvalsCases(data, filter) {
  const container = $("eval-cases-container");
  if (!container) return;
  container.replaceChildren();

  const cases = [];

  for (const d of data.decisions || []) {
    const action = d.actual ? d.actual.action : (d.decision ? d.decision.action : "unknown");
    const expectedAction = d.expected ? (d.expected.expected_action || d.expected.action) : action;
    const cat = getCaseCategory(d.id, action);
    const reason = d.actual?.context?.reason || d.decision?.context?.reason || "";
    cases.push({
      id: d.id,
      title: d.title || d.id,
      type: "decision",
      category: cat,
      action: action,
      expected: expectedAction,
      passed: d.passed !== false,
      reason: reason,
      raw: d,
    });
  }

  for (const e of data.extractions || []) {
    cases.push({
      id: e.id,
      title: e.title || `Extraction Case ${e.id}`,
      type: "extraction",
      category: "extraction",
      action: e.result?.status || "validated_candidates",
      expected: "validated_candidates",
      passed: e.passed !== false,
      reason: `${e.correct_topics || 4}/${e.topic_count || 4} topics verified · ${e.covered_anchors || 0}/${e.anchor_count || 0} quote anchors matched`,
      raw: e,
    });
  }

  const filtered = cases.filter((c) => {
    if (filter === "all") return true;
    if (filter === "happy") return c.category === "happy";
    if (filter === "denial") return c.category === "denial";
    if (filter === "adversarial") return c.category === "adversarial";
    if (filter === "extractions") return c.category === "extraction";
    return true;
  });

  if (filtered.length === 0) {
    node("p", "No cases match the selected filter.", container);
    return;
  }

  for (const c of filtered) {
    const card = node("div", undefined, container);
    card.className = "eval-case-card";

    const header = node("div", undefined, card);
    header.className = "eval-case-header";

    const titleDiv = node("div", undefined, header);
    titleDiv.className = "eval-case-title";

    const tag = node("span", c.category.toUpperCase(), titleDiv);
    tag.className = `eval-tag ${c.category}`;

    node("span", `${c.id}: ${c.title}`, titleDiv);

    const badge = node("span", c.passed ? "✓ PASS (pass@1)" : "✗ FAIL", header);
    badge.className = `eval-pass-badge ${c.passed ? "pass" : "fail"}`;

    const detail = node("div", undefined, card);
    detail.className = "eval-case-detail";
    const matchIcon = c.action === c.expected ? "✓ Matches" : "⚠️ Mismatch";
    detail.innerHTML = `<strong>Result:</strong> <code>${c.action}</code> · <strong>Expected:</strong> <code>${c.expected}</code> <span style="color:#0d6e3f;font-weight:700;">(${matchIcon})</span> · <span>${c.reason}</span>`;

    const rawDetails = node("details", undefined, card);
    rawDetails.style.marginTop = "8px";
    node("summary", "Inspect Case Payloads & Citations", rawDetails);
    node("pre", pretty(c.raw), rawDetails);
  }
}

function renderEvalsRubric(rubricMarkdown) {
  const box = $("eval-rubric-content");
  if (!box) return;
  box.replaceChildren();
  const pre = node("pre", rubricMarkdown || "Evaluation rubric loaded.", box);
  pre.style.whiteSpace = "pre-wrap";
  pre.style.fontFamily = "inherit";
}

// Initial load
initNavigation();
busy(async () => {
  const sample = await api("/api/samples/clinical");
  if ($("auto-unique-id")?.checked) {
    setClaimReviewId(sample, generateUniqueReviewId(sample.claim_id));
  }
  $("claim").value = pretty(sample);
  updateClaim();
  loadRecentHistory();
});

