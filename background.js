/**
 * The Other Side — Chrome Extension
 * background.js — Service Worker (Manifest V3)
 *
 * Replace API_BASE with your Cloud Run URL after deploying.
 * deploy.sh prints it at the end.
 */

"use strict";

const API_BASE = "https://your-service-url.run.app"; // ← deploy.sh will print your URL

// ─────────────────────────────────────────────────────────────
// CONTEXT MENUS
// ─────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "flip-selection", title: "◐ Flip this perspective",  contexts: ["selection"] });
  chrome.contextMenus.create({ id: "flip-image",     title: "◐ Flip this image",        contexts: ["image"]     });
  chrome.contextMenus.create({ id: "flip-video",     title: "◐ Flip this video",        contexts: ["video"]     });
  chrome.contextMenus.create({ id: "flip-link",      title: "◐ Flip this article",      contexts: ["link"]      });
  chrome.contextMenus.create({ id: "flip-page",      title: "◐ Flip this page",         contexts: ["page"]      });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let type, content;
  switch (info.menuItemId) {
    case "flip-selection": type = "text";      content = info.selectionText;             break;
    case "flip-image":     type = "image_url"; content = info.srcUrl;                    break;
    case "flip-video":     type = "video_url"; content = info.srcUrl || info.pageUrl;    break;
    case "flip-link":      type = "url";       content = info.linkUrl;                   break;
    case "flip-page":      type = "url";       content = info.pageUrl;                   break;
    default: return;
  }

  const { preferredAngle } = await chrome.storage.local.get(["preferredAngle"]);
  await chrome.storage.local.set({
    pendingFlip: { type, content, angle: preferredAngle || "empathy", sessionId: crypto.randomUUID() },
    flipStatus: "pending",
  });
  await chrome.action.openPopup();
});

// ─────────────────────────────────────────────────────────────
// MESSAGE HANDLER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "RUN_FLIP") {
    runFlip(message.payload).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.type === "GET_ANGLES") {
    fetchAngles().then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.type === "SUBMIT_FEEDBACK") {
    submitFeedback(message.payload).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.type === "GENERATE_VIDEO") {
    generateVideo(message.payload).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
});

// ─────────────────────────────────────────────────────────────
// CORE FLIP
// ─────────────────────────────────────────────────────────────

async function runFlip({ type, content, angle, sessionId }) {
  // Map context menu type to media_type for the backend
  const mediaTypeMap = {
    text:      "text",
    url:       "text",
    image_url: "image",
    video_url: "video",
  };
  const media_type = mediaTypeMap[type] || "text";

  // Layer 1 guardrail + session log
  const flipRes = await fetch(`${API_BASE}/flip`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ situation: content, angle, media_type, session_id: sessionId }),
  });
  if (!flipRes.ok) throw new Error(`API error: ${flipRes.status}`);
  const flipData = await flipRes.json();

  if (flipData.declined) {
    return { declined: true, message: flipData.message, sessionId };
  }

  // Run ADK agent
  const adkRes = await fetch(`${API_BASE}${flipData.adk_run_endpoint}`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(flipData.adk_run_payload),
  });
  if (!adkRes.ok) throw new Error(`ADK error: ${adkRes.status}`);
  const adkData = await adkRes.json();

  return { declined: false, result: adkData, sessionId, angle, media_type };
}

// ─────────────────────────────────────────────────────────────
// VIDEO GENERATION — async job polling
// ─────────────────────────────────────────────────────────────

async function generateVideo({ headline, the_other_side, facts, closing_prompt, generation_payload, angle, session_id }) {
  // Kick off the job
  const startRes = await fetch(`${API_BASE}/generate-video`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ headline, the_other_side, facts, closing_prompt, generation_payload, angle, session_id }),
  });
  if (!startRes.ok) throw new Error(`Video start failed: ${startRes.status}`);
  const { job_id } = await startRes.json();

  // Poll until done (max 3 minutes)
  const maxAttempts = 36; // 36 × 5s = 3 minutes
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 5000));
    const statusRes = await fetch(`${API_BASE}/video-status/${job_id}`);
    if (!statusRes.ok) continue;
    const status = await statusRes.json();

    if (status.status === "completed") return { video_url: status.video_url };
    if (status.status === "failed")    throw new Error(status.error || "Video generation failed");
  }
  throw new Error("Video generation timed out");
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

async function fetchAngles() {
  const res = await fetch(`${API_BASE}/angles`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

async function submitFeedback(payload) {
  const res = await fetch(`${API_BASE}/feedback`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Feedback error: ${res.status}`);
  return res.json();
}
