/**
 * The Other Side — Chrome Extension
 * popup.js — Popup controller
 * Output: headline + the_other_side + facts + closing_prompt
 */

"use strict";

// ── STATE ─────────────────────────────────────────────────────

const state = {
  angle:         "empathy",
  angles:        [],
  sessionId:     null,
  feedbackNew:   null,
  fairnessScore: null,
  qualityScore:  null,
};

// ── DOM ───────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function show(id)  { const el = $(id); if (el) { el.style.display = "flex"; el.style.flexDirection = "column"; } }
function hide(id)  { const el = $(id); if (el) el.style.display = "none"; }

function showOnly(id) {
  ["v-input","v-load","v-result","v-declined"].forEach(v => hide(v));
  show(id);
}

// ── INIT ──────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await loadAngles();
  await checkPending();
  bindEvents();
  showOnly("v-input");
});

// ── ANGLES ────────────────────────────────────────────────────

async function loadAngles() {
  const res = await msg({ type: "GET_ANGLES" });
  state.angles = res?.angles ?? [
    { id: "empathy",  label: "🪞 Empathy Mirror"    },
    { id: "conflict", label: "⚖️ Conflict Mediator"  },
    { id: "bias",     label: "🔄 Bias Flipper"       },
    { id: "history",  label: "📜 History Retold"     },
    { id: "devil",    label: "😈 Devil's Advocate"   },
  ];

  const { preferredAngle } = await chrome.storage.local.get(["preferredAngle"]);
  if (preferredAngle) state.angle = preferredAngle;

  renderLenses();
}

function renderLenses() {
  const c = $("lenses");
  c.innerHTML = "";
  state.angles.forEach(a => {
    const b = document.createElement("button");
    b.className = `lens${a.id === state.angle ? " on" : ""}`;
    b.textContent = a.label;
    b.dataset.id = a.id;
    b.onclick = () => selectLens(a.id);
    c.appendChild(b);
  });
}

function selectLens(id) {
  state.angle = id;
  chrome.storage.local.set({ preferredAngle: id });
  document.querySelectorAll(".lens").forEach(b => b.classList.toggle("on", b.dataset.id === id));
}

// ── PENDING FLIP (from context menu) ─────────────────────────

async function checkPending() {
  const { pendingFlip, flipStatus } = await chrome.storage.local.get(["pendingFlip","flipStatus"]);
  if (pendingFlip && flipStatus === "pending") {
    await chrome.storage.local.remove(["pendingFlip","flipStatus"]);
    if (pendingFlip.angle) selectLens(pendingFlip.angle);
    if (pendingFlip.type === "text" || pendingFlip.type === "url") {
      $("txt").value = pendingFlip.content || "";
    }
    await runFlip(pendingFlip.content, pendingFlip.type);
  }
}

// ── EVENTS ────────────────────────────────────────────────────

function bindEvents() {
  $("flip-btn").onclick = async () => {
    const t = $("txt").value.trim();
    if (t) await runFlip(t, "text");
  };

  $("txt").addEventListener("keydown", async e => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      const t = $("txt").value.trim();
      if (t) await runFlip(t, "text");
    }
  });

  $("back-btn").onclick     = resetToInput;
  $("declined-back").onclick = resetToInput;

  $("fb-yes").onclick = () => setFbNew(true);
  $("fb-no").onclick  = () => setFbNew(false);

  buildStars("stars-f", v => state.fairnessScore = v);
  buildStars("stars-q", v => state.qualityScore  = v);

  $("submit-fb").onclick = submitFeedback;
}

function setFbNew(val) {
  state.feedbackNew = val;
  $("fb-yes").classList.toggle("on",  val === true);
  $("fb-no").classList.toggle("on",   val === false);
}

function buildStars(containerId, onSelect) {
  const c = $(containerId);
  for (let i = 1; i <= 5; i++) {
    const s = document.createElement("button");
    s.className = "star";
    s.textContent = "★";
    s.dataset.v = i;
    s.onclick = () => {
      c.querySelectorAll(".star").forEach(el => el.classList.toggle("on", +el.dataset.v <= i));
      onSelect(i);
    };
    c.appendChild(s);
  }
}

// ── RUN FLIP ──────────────────────────────────────────────────

async function runFlip(content, type = "text") {
  showOnly("v-load");
  hideErr();

  const sessionId = crypto.randomUUID();
  const response  = await msg({ type: "RUN_FLIP", payload: { type, content, angle: state.angle, sessionId } });

  if (!response || response.error) {
    showOnly("v-input");
    showErr(response?.error ?? "Something went wrong. Please try again.");
    return;
  }

  state.sessionId = response.sessionId ?? sessionId;

  if (response.declined) {
    $("declined-msg").textContent = response.message;
    showOnly("v-declined");
    return;
  }

  // ADK returns array of events; extract text from first content part
  const adkEvents = response.result;
  let rawText = "";
  if (Array.isArray(adkEvents)) {
    for (const ev of adkEvents) {
      const parts = ev?.content?.parts ?? [];
      for (const p of parts) {
        if (p.text) { rawText += p.text; }
      }
    }
  } else {
    rawText = JSON.stringify(adkEvents ?? {});
  }
  renderResult(rawText);
}

// ── RENDER ────────────────────────────────────────────────────

function renderResult(raw) {
  // Parse bridge JSON from ADK response
  const text  = typeof raw === "string" ? raw : JSON.stringify(raw ?? {});
  const clean = text.replace(/^```(?:json)?\s*/m,"").replace(/\s*```$/m,"").trim();
  let data = null;
  try {
    const s = clean.indexOf("{"), e = clean.lastIndexOf("}");
    if (s !== -1 && e !== -1) data = JSON.parse(clean.slice(s, e + 1));
  } catch (_) {}

  const headline      = data?.headline       ?? "";
  const otherSide     = data?.the_other_side ?? "";
  const facts         = data?.facts          ?? [];
  const closingPrompt = data?.closing_prompt ?? "";

  // Bridge
  if (headline || otherSide) {
    $("bridge-hl").textContent   = headline;
    $("bridge-body").textContent = otherSide;
    show("bridge-card");
    $("bridge-card").style.display = "block";
  }

  // Facts
  if (facts.length > 0) {
    const list = $("facts-list");
    list.innerHTML = "";
    facts.forEach(f => {
      const d = document.createElement("div");
      d.className = "fact-item";
      const lvl = f.confidence ?? "moderate";
      d.innerHTML = `
        ${escHtml(f.fact)}
        <span class="badge ${lvl}">${lvl}</span>
        ${f.source_hint ? `<div class="fact-src">Source: ${escHtml(f.source_hint)}</div>` : ""}
      `;
      list.appendChild(d);
    });
    $("facts-card").style.display = "block";
  }

  // Closing
  if (closingPrompt) {
    $("closing-txt").textContent   = closingPrompt;
    $("closing-card").style.display = "block";
  }

  // Feedback
  $("fb-card").style.display = "block";

  showOnly("v-result");
}

// ── FEEDBACK ──────────────────────────────────────────────────

async function submitFeedback() {
  if (state.fairnessScore === null || state.qualityScore === null) {
    const btn = $("submit-fb");
    btn.textContent = "Please rate both ☝️";
    setTimeout(() => btn.textContent = "Submit feedback", 2000);
    return;
  }

  await msg({
    type: "SUBMIT_FEEDBACK",
    payload: {
      session_id:      state.sessionId,
      perspective_new: state.feedbackNew ?? false,
      fairness_score:  state.fairnessScore,
      quality_score:   state.qualityScore,
    },
  });

  $("fb-card").innerHTML = `
    <div style="text-align:center;padding:8px 0;color:#4ade80;font-size:12px">
      ✓ Feedback received.
    </div>
  `;
}

// ── RESET ─────────────────────────────────────────────────────

function resetToInput() {
  ["bridge-card","facts-card","closing-card","fb-card"].forEach(id => {
    const el = $(id);
    if (el) el.style.display = "none";
  });
  $("txt").value        = "";
  state.sessionId       = null;
  state.feedbackNew     = null;
  state.fairnessScore   = null;
  state.qualityScore    = null;
  hideErr();
  showOnly("v-input");
}

// ── HELPERS ───────────────────────────────────────────────────

function showErr(txt) {
  const el = $("err");
  el.textContent = txt;
  el.style.display = "block";
}

function hideErr() {
  $("err").style.display = "none";
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}

function msg(payload) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage(payload, res => {
      resolve(chrome.runtime.lastError ? { error: chrome.runtime.lastError.message } : res);
    });
  });
}
