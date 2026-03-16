/**
 * The Other Side — Chrome Extension
 * content.js — Content Script
 *
 * - In-page video pointer overlay
 * - Inline result panel showing The Bridge (headline + the_other_side + facts + closing)
 */

(function () {
  "use strict";

  // ── CONFIG — swap for Cloud Run URL when deploying ──────────
  const API_BASE = "https://the-other-side-497596932195.us-central1.run.app";

  // ── IN-PAGE VIDEO POINTER ──────────────────────────────────

  let overlay     = null;
  let targetVideo = null;

  function createOverlay() {
    const div = document.createElement("div");
    div.id = "__tos_overlay__";
    div.innerHTML = `<span style="font-size:15px">◐</span><span style="font-size:12px;font-weight:600;margin-left:7px">Flip this perspective</span>`;
    Object.assign(div.style, {
      position: "fixed", display: "none", zIndex: "2147483647",
      background: "linear-gradient(135deg,#1a0a2e,#0e0e1a)",
      border: "1.5px solid #a78bfa", borderRadius: "10px",
      padding: "7px 14px", cursor: "pointer", color: "#eeeaf8",
      fontFamily: "-apple-system,sans-serif", userSelect: "none",
      boxShadow: "0 4px 20px rgba(167,139,250,0.3)",
      backdropFilter: "blur(10px)",
    });
    div.addEventListener("click", () => {
      if (!targetVideo) return;
      // Extract YouTube video title + description for better context
      const pageUrl = window.location.href;
      let situation = pageUrl;
      if (pageUrl.includes("youtube.com") || pageUrl.includes("youtu.be")) {
        const title = document.querySelector("h1.ytd-video-primary-info-renderer, h1.style-scope.ytd-watch-metadata, yt-formatted-string.ytd-watch-metadata")?.textContent?.trim()
                   || document.title?.replace(" - YouTube","")?.trim()
                   || "";
        const desc  = document.querySelector("#description-inline-expander, #snippet-text, ytd-text-inline-expander")?.textContent?.trim()?.slice(0,300) || "";
        situation = title ? `[YouTube Video] "${title}"
${desc ? "Description: " + desc : "URL: " + pageUrl}` : pageUrl;
      }
      triggerFlip("url", situation);
    });
    document.body.appendChild(div);
    return div;
  }

  function attachVideoListeners() {
    // Handle both video and audio elements
    // For YouTube, also target the player container
    const ytPlayer = document.querySelector("#movie_player, .html5-video-player, ytd-player");
    if (ytPlayer && !ytPlayer.dataset.tosAttached) {
      ytPlayer.dataset.tosAttached = "true";
      ytPlayer.addEventListener("mouseenter", () => {
        targetVideo = { src: window.location.href };
        if (!overlay) overlay = createOverlay();
        const r = ytPlayer.getBoundingClientRect();
        overlay.style.top  = `${r.top + 12}px`;
        overlay.style.left = `${r.left + 12}px`;
        overlay.style.display = "flex";
        overlay.style.alignItems = "center";
      });
      ytPlayer.addEventListener("mouseleave", e => {
        if (e.relatedTarget === overlay) return;
        if (overlay) overlay.style.display = "none";
        targetVideo = null;
      });
    }
    document.querySelectorAll("video, audio").forEach(media => {
      if (media.dataset.tosAttached) return;
      media.dataset.tosAttached = "true";
      media.addEventListener("mouseenter", () => {
        targetVideo = media;
        if (!overlay) overlay = createOverlay();
        const r = media.getBoundingClientRect();
        overlay.style.top  = `${r.top + 8}px`;
        overlay.style.left = `${r.left + 8}px`;
        overlay.style.display = "flex";
        overlay.style.alignItems = "center";
      });
      media.addEventListener("mouseleave", e => {
        if (e.relatedTarget === overlay) return;
        if (overlay) overlay.style.display = "none";
        targetVideo = null;
      });
    });

    // YouTube Music: attach to the player bar since audio element is hidden
    const ytmBar = document.querySelector("ytmusic-player-bar, .ytmusic-player-bar, #layout ytmusic-app");
    if (ytmBar && !ytmBar.dataset.tosAttached) {
      ytmBar.dataset.tosAttached = "true";
      ytmBar.addEventListener("mouseenter", () => {
        if (!overlay) overlay = createOverlay();
        const r = ytmBar.getBoundingClientRect();
        overlay.style.top  = `${r.top + 8}px`;
        overlay.style.left = `${r.left + 80}px`;
        overlay.style.display = "flex";
        overlay.style.alignItems = "center";
        // point to current page URL as the track source
        targetVideo = { src: window.location.href, currentSrc: window.location.href };
      });
      ytmBar.addEventListener("mouseleave", e => {
        if (e.relatedTarget === overlay) return;
        if (overlay) overlay.style.display = "none";
        targetVideo = null;
      });
    }
  }

  const observer = new MutationObserver(attachVideoListeners);
  observer.observe(document.body, { childList: true, subtree: true });
  attachVideoListeners();

  document.addEventListener("mouseover", e => {
    if (overlay && !overlay.contains(e.target) && !e.target.closest("video") && !e.target.closest("audio") && !e.target.closest("ytmusic-player-bar")) {
      overlay.style.display = "none";
      targetVideo = null;
    }
  });

  // ── TRIGGER FLIP ──────────────────────────────────────────

  async function triggerFlip(mediaType, content) {
    if (overlay) overlay.style.display = "none";
    showLoadingToast();
    try {
      const { preferredAngle } = await chrome.storage.local.get(["preferredAngle"]);
      const angle     = preferredAngle || "empathy";
      const sessionId = crypto.randomUUID();

      // Step 1: call /flip to get ADK payload
      const flipRes = await fetch(API_BASE + "/flip", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation: content, angle, media_type: mediaType, session_id: sessionId }),
      });
      if (!flipRes.ok) throw new Error("Server error: " + flipRes.status);
      const flipData = await flipRes.json();
      if (flipData.declined) { renderInlineResult({ declined: true, message: flipData.message, sessionId }); return; }
      // Step 2: call /adk/run
      const adkRes = await fetch(API_BASE + flipData.adk_run_endpoint, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(flipData.adk_run_payload),
      });
      if (!adkRes.ok) throw new Error("ADK error: " + adkRes.status);
      const adkData = await adkRes.json();
      let rawText = "";
      if (Array.isArray(adkData)) {
        for (const ev of adkData) {
          const parts = ev?.content?.parts ?? [];
          for (const p of parts) { if (p.text) rawText += p.text; }
        }
      }
      // Parse result to check if we should generate video
      const isYouTube = window.location.href.includes("youtube.com") || window.location.href.includes("youtu.be");
      if (isYouTube) {
        // Show text result first, then trigger video generation
        renderInlineResult({ declined: false, result: rawText, sessionId, generateVideo: true, adkData });
      } else {
        renderInlineResult({ declined: false, result: rawText, sessionId });
      }
    } catch (e) {
      showErrorToast(e.message);
    }
  }

  // ── LOADING TOAST ─────────────────────────────────────────

  function showLoadingToast() {
    removeById("__tos_toast__");
    const t = document.createElement("div");
    t.id = "__tos_toast__";
    t.innerHTML = `<span style="font-size:16px">◐</span><span style="margin-left:8px">Looking at the other side…</span>`;
    Object.assign(t.style, {
      position: "fixed", bottom: "24px", right: "24px", zIndex: "2147483647",
      display: "flex", alignItems: "center",
      background: "#13131f", border: "1.5px solid #a78bfa44",
      borderRadius: "12px", padding: "12px 18px",
      color: "#eeeaf8", fontFamily: "-apple-system,sans-serif",
      fontSize: "13px", fontWeight: "600",
      boxShadow: "0 8px 30px rgba(0,0,0,0.5)",
    });
    document.body.appendChild(t);
  }

  // ── INLINE RESULT PANEL ───────────────────────────────────

  function renderInlineResult(response) {
    removeById("__tos_toast__");
    removeById("__tos_panel__");

    if (!response || response.error) { showErrorToast(response?.error || "Something went wrong."); return; }
    if (response.declined) { showDeclinedPanel(response.message); return; }

    // Parse the bridge data from ADK response
    const raw = typeof response.result === "string" ? response.result : JSON.stringify(response.result || {});
    let data = null;
    try {
      const clean = raw.replace(/^```(?:json)?\s*/m,"").replace(/\s*```$/m,"").trim();
      const s = clean.indexOf("{"), e = clean.lastIndexOf("}");
      if (s !== -1 && e !== -1) data = JSON.parse(clean.slice(s, e+1));
    } catch(_) {}

    const headline      = data?.headline      || "";
    const otherSide     = data?.the_other_side || "";
    const facts         = data?.facts         || [];
    const closingPrompt = data?.closing_prompt || "What shifted for you?";
    const angleLabel    = data?.angle_label    || "◐ The Other Side";

    const panel = document.createElement("div");
    panel.id = "__tos_panel__";

    const factsHTML = facts.slice(0,3).map(f => `
      <div style="background:#0d0d1e;border-radius:8px;padding:8px 10px;margin-bottom:6px;font-size:11px;color:#c4c0d8;line-height:1.5">
        ${f.fact}
        <span style="display:inline-block;font-size:9px;padding:1px 5px;border-radius:4px;margin-left:5px;background:${f.confidence==="high"?"#4ade8018":f.confidence==="uncertain"?"#f8717118":"#f0c96a18"};color:${f.confidence==="high"?"#4ade80":f.confidence==="uncertain"?"#f87171":"#f0c96a"}">${f.confidence||"moderate"}</span>
        ${f.source_hint ? `<div style="font-size:9px;color:#52506a;margin-top:3px">Source: ${f.source_hint}</div>` : ""}
      </div>
    `).join("");

    panel.innerHTML = `
      <div style="
        position:fixed;bottom:24px;right:24px;width:360px;max-height:82vh;
        overflow-y:auto;background:#07070e;border:1.5px solid #a78bfa33;
        border-radius:16px;padding:18px;z-index:2147483647;
        box-shadow:0 8px 40px rgba(0,0,0,0.75);font-family:-apple-system,sans-serif;
        color:#eeeaf8;
      ">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
          <div style="font-size:12px;font-weight:700;color:#a78bfa">${angleLabel}</div>
          <button id="__tos_close__" style="background:none;border:none;color:#52506a;cursor:pointer;font-size:16px;padding:0">✕</button>
        </div>

        ${headline ? `
          <div style="background:#0f0e06;border:1px solid #f0c96a33;border-radius:12px;padding:14px 16px;margin-bottom:12px">
            <div style="font-size:14px;font-weight:800;color:#f0c96a;margin-bottom:8px;line-height:1.4">${headline}</div>
            <div style="font-size:12px;color:#9a8850;line-height:1.65">${otherSide}</div>
          </div>
        ` : `<div style="font-size:12px;color:#52506a;margin-bottom:12px">Processing complete — check full result in popup.</div>`}

        ${factsHTML ? `
          <div style="font-size:9px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:#52506a;margin-bottom:8px">Grounding facts</div>
          ${factsHTML}
        ` : ""}

        <div style="background:#0d060f;border:1px solid #e879f922;border-radius:10px;padding:12px;margin-bottom:14px;font-size:12px;color:#e879f9;font-style:italic;line-height:1.6">
          ${closingPrompt}
        </div>

        <div id="__tos_video__"></div>
        <div style="display:flex;gap:8px">
          <button data-fb="true"  style="flex:1;background:#a78bfa18;border:1px solid #a78bfa44;border-radius:8px;color:#a78bfa;padding:8px;cursor:pointer;font-size:11px;font-family:-apple-system,sans-serif">Yes, new to me</button>
          <button data-fb="false" style="flex:1;background:#52506a18;border:1px solid #52506a44;border-radius:8px;color:#52506a;padding:8px;cursor:pointer;font-size:11px;font-family:-apple-system,sans-serif">Already knew this</button>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    panel.querySelector("#__tos_close__").addEventListener("click", () => panel.remove());

    // Auto-trigger video generation for YouTube
    if (response.generateVideo && response.adkData) {
      (async () => {
      const videoContainer = panel.querySelector("#__tos_video__");
      if (videoContainer) {
        videoContainer.innerHTML = `<div style="font-size:11px;color:#a78bfa;margin-top:12px">🎬 Generating flip video...</div>`;
        // Build video payload from ADK result
        let parsedData = null;
        try {
          const raw = typeof response.result === "string" ? response.result : JSON.stringify(response.result || {});
          const clean = raw.replace(/^```(?:json)?\s*/m,"").replace(/\s*```$/m,"").trim();
          const s = clean.indexOf("{"), e = clean.lastIndexOf("}");
          if (s !== -1 && e !== -1) parsedData = JSON.parse(clean.slice(s, e+1));
        } catch(_) {}

        if (parsedData) {
          const videoPayload = {
            headline: parsedData.headline || "",
            the_other_side: parsedData.the_other_side || "",
            facts: parsedData.facts || [],
            closing_prompt: parsedData.closing_prompt || "",
            angle: "empathy",
            session_id: response.sessionId,
            generation_payload: {
              visual_prompt: `Cinematic scenes for: ${parsedData.headline}`,
              voice_profile: "warm",
              video_script: [
                { scene: 1, frame_prompt: `Cinematic emotional scene: ${parsedData.headline}, soft lighting, thoughtful person`, narration: parsedData.headline || "" },
                { scene: 2, frame_prompt: `A person reflecting quietly, warm indoor light, cinematic depth of field`, narration: (parsedData.the_other_side || "").slice(0, 200) },
                { scene: 3, frame_prompt: `Two people connecting warmly, golden hour light, hopeful atmosphere`, narration: parsedData.closing_prompt || "What would change if you assumed positive intent?" }
              ]
            }
          };

          try {
            const vRes = await fetch(API_BASE + "/generate-video", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(videoPayload)
            });
            const { job_id } = await vRes.json();

            // Poll for video completion
            for (let i = 0; i < 36; i++) {
              await new Promise(r => setTimeout(r, 5000));
              const statusRes = await fetch(API_BASE + "/video-status/" + job_id);
              const statusData = await statusRes.json();
              if (statusData.status === "completed" && statusData.video_url) {
                videoContainer.innerHTML = `
                  <div style="margin-top:12px">
                    <div style="font-size:10px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:#52506a;margin-bottom:6px">Flip Video</div>
                    <video controls style="width:100%;border-radius:10px;border:1px solid #a78bfa33" src="${statusData.video_url}"></video>
                  </div>`;
                break;
              }
              if (statusData.status === "failed") {
                videoContainer.innerHTML = `<div style="font-size:11px;color:#f87171;margin-top:8px">Video generation failed.</div>`;
                break;
              }
              videoContainer.innerHTML = `<div style="font-size:11px;color:#a78bfa;margin-top:12px">🎬 Generating flip video... (${i*5}s)</div>`;
            }
          } catch(e) {
            videoContainer.innerHTML = `<div style="font-size:11px;color:#f87171;margin-top:8px">Video error: ${e.message}</div>`;
          }
        }
      })();
    }

    panel.querySelectorAll("[data-fb]").forEach(btn => {
      btn.addEventListener("click", () => {
        chrome.runtime.sendMessage({
          type: "SUBMIT_FEEDBACK",
          payload: {
            session_id:      response.sessionId,
            perspective_new: btn.dataset.fb === "true",
            fairness_score:  4,
            quality_score:   4,
          },
        });
        panel.remove();
      });
    });
  }

  function showDeclinedPanel(message) {
    removeById("__tos_panel__");
    const p = document.createElement("div");
    p.id = "__tos_panel__";
    p.innerHTML = `
      <div style="position:fixed;bottom:24px;right:24px;width:300px;background:#120808;border:1.5px solid #f8717144;border-radius:14px;padding:18px;z-index:2147483647;font-family:-apple-system,sans-serif">
        <div style="font-size:13px;font-weight:700;color:#f87171;margin-bottom:8px">◐ Outside our range</div>
        <div style="font-size:12px;color:#8a5050;line-height:1.6;margin-bottom:12px">${message}</div>
        <button style="background:none;border:1px solid #f8717133;border-radius:8px;color:#f87171;padding:6px 12px;cursor:pointer;font-size:11px;font-family:-apple-system,sans-serif" onclick="this.closest('#__tos_panel__').remove()">Got it</button>
      </div>
    `;
    document.body.appendChild(p);
    setTimeout(() => p?.remove(), 8000);
  }

  function showErrorToast(msg) {
    const t = document.createElement("div");
    Object.assign(t.style, {
      position: "fixed", bottom: "24px", right: "24px", zIndex: "2147483647",
      background: "#120808", border: "1px solid #f8717133", borderRadius: "12px",
      padding: "12px 16px", color: "#f87171",
      fontFamily: "-apple-system,sans-serif", fontSize: "12px",
    });
    t.textContent = `◐ ${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 5000);
  }

  function removeById(id) {
    document.getElementById(id)?.remove();
  }

  chrome.runtime.onMessage.addListener(msg => {
    if (msg.type === "FLIP_RESULT") renderInlineResult(msg.payload);
  });
})();

// ── TEXT SELECTION BUBBLE ─────────────────────────────────────

(function() {
  let selectionBtn = null;

  function createSelectionBtn() {
    const btn = document.createElement("div");
    btn.id = "__tos_sel_btn__";
    btn.innerHTML = `<span style="font-size:13px">◐</span><span style="font-size:11px;font-weight:600;margin-left:6px">Flip this perspective</span>`;
    Object.assign(btn.style, {
      position: "fixed",
      zIndex: "2147483647",
      background: "linear-gradient(135deg,#1a0a2e,#0e0e1a)",
      border: "1.5px solid #a78bfa",
      borderRadius: "10px",
      padding: "6px 13px",
      cursor: "pointer",
      color: "#eeeaf8",
      fontFamily: "-apple-system,sans-serif",
      userSelect: "none",
      boxShadow: "0 4px 20px rgba(167,139,250,0.35)",
      backdropFilter: "blur(10px)",
      display: "flex",
      alignItems: "center",
      fontSize: "12px",
      transition: "opacity 0.15s",
    });
    document.body.appendChild(btn);
    return btn;
  }

  document.addEventListener("mouseup", (e) => {
    // Remove old button
    if (selectionBtn) { selectionBtn.remove(); selectionBtn = null; }

    // Ignore clicks inside our own panels
    if (e.target.closest("#__tos_panel__") || e.target.closest("#__tos_sel_btn__")) return;

    setTimeout(() => {
      const sel = window.getSelection();
      const text = sel?.toString().trim();
      if (!text || text.length < 10) return;

      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();

      selectionBtn = createSelectionBtn();
      // Position above the selection
      const top = rect.top - 48;
      const left = rect.left + (rect.width / 2) - 90;
      selectionBtn.style.top = `${Math.max(8, top)}px`;
      selectionBtn.style.left = `${Math.max(8, left)}px`;
      selectionBtn.style.position = "fixed";

      selectionBtn.addEventListener("click", () => {
        selectionBtn.remove();
        selectionBtn = null;
        triggerFlip("text", text);
        window.getSelection().removeAllRanges();
      });
    }, 10);
  });

  document.addEventListener("mousedown", (e) => {
    if (selectionBtn && !selectionBtn.contains(e.target)) {
      selectionBtn.remove();
      selectionBtn = null;
    }
  });
})();
