/**
 * Approval Overlay Panel for V16 Pipeline
 * 
 * Floating bottom-right card that shows pending improvement proposals.
 * User can thumbs-up or thumbs-down each item. Polls every 30s.
 */
(() => {
  "use strict";

  const POLL_INTERVAL = 30000; // 30 seconds
  const FADE_DELAY = 3000; // 3s before "All clear" badge fades

  let items = [];
  let currentIndex = 0;
  let overlay = null;
  let pollTimer = null;

  // --- DOM Construction ---

  function createOverlay() {
    const el = document.createElement("div");
    el.id = "approval-overlay";
    el.innerHTML = `
      <style>
        #approval-overlay {
          position: fixed;
          bottom: 20px;
          right: 20px;
          z-index: 9990;
          font-family: Inter, system-ui, sans-serif;
          font-size: 13px;
          pointer-events: auto;
        }
        #approval-overlay .ao-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 14px;
          background: rgba(10, 23, 19, 0.92);
          border: 1px solid #376453;
          border-radius: 20px;
          color: #8edbb8;
          cursor: pointer;
          font-weight: 600;
          font-size: 12px;
          backdrop-filter: blur(8px);
          transition: opacity 0.4s, transform 0.3s;
        }
        #approval-overlay .ao-badge:hover {
          background: rgba(14, 34, 28, 0.95);
          border-color: #8edbb8;
        }
        #approval-overlay .ao-badge.ao-clear {
          color: #6abf95;
          cursor: default;
        }
        #approval-overlay .ao-badge.ao-fade {
          opacity: 0;
          transform: translateY(10px);
        }
        #approval-overlay .ao-card {
          width: 320px;
          background: rgba(10, 23, 19, 0.95);
          border: 1px solid #376453;
          border-radius: 12px;
          overflow: hidden;
          backdrop-filter: blur(12px);
          box-shadow: 0 8px 32px rgba(0,0,0,0.4);
          animation: ao-slide-in 0.25s ease-out;
        }
        @keyframes ao-slide-in {
          from { opacity: 0; transform: translateY(12px) scale(0.96); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        #approval-overlay .ao-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 14px;
          border-bottom: 1px solid #244238;
          background: rgba(7, 16, 13, 0.6);
        }
        #approval-overlay .ao-card-header span {
          color: #8ca69b;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }
        #approval-overlay .ao-counter {
          color: #6abf95;
          font-size: 11px;
          font-weight: 600;
        }
        #approval-overlay .ao-card-body {
          padding: 14px;
        }
        #approval-overlay .ao-title {
          color: #e8f2ed;
          font-weight: 600;
          font-size: 14px;
          margin: 0 0 6px;
          line-height: 1.3;
        }
        #approval-overlay .ao-desc {
          color: #8ca69b;
          font-size: 12px;
          margin: 0 0 10px;
          line-height: 1.4;
          max-height: 48px;
          overflow: hidden;
        }
        #approval-overlay .ao-thumb {
          width: 100%;
          max-height: 140px;
          object-fit: contain;
          border-radius: 6px;
          border: 1px solid #244238;
          margin-bottom: 10px;
          background: #050a08;
        }
        #approval-overlay .ao-actions {
          display: flex;
          gap: 10px;
          padding: 10px 14px;
          border-top: 1px solid #244238;
          background: rgba(7, 16, 13, 0.4);
        }
        #approval-overlay .ao-btn {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 5px;
          padding: 9px 0;
          border: none;
          border-radius: 6px;
          font-size: 14px;
          font-weight: 700;
          cursor: pointer;
          transition: transform 0.15s, opacity 0.15s;
        }
        #approval-overlay .ao-btn:hover {
          transform: scale(1.04);
        }
        #approval-overlay .ao-btn:active {
          transform: scale(0.96);
        }
        #approval-overlay .ao-btn.ao-approve {
          background: #1a4d35;
          color: #8edbb8;
          border: 1px solid #376453;
        }
        #approval-overlay .ao-btn.ao-reject {
          background: #3d1a1a;
          color: #f08080;
          border: 1px solid #5c3030;
        }
        #approval-overlay .ao-btn.ao-approve:hover { background: #1f5c3e; }
        #approval-overlay .ao-btn.ao-reject:hover { background: #4a2020; }
        #approval-overlay .ao-collapse-btn {
          background: none;
          border: none;
          color: #8ca69b;
          cursor: pointer;
          font-size: 14px;
          padding: 2px 6px;
          border-radius: 4px;
        }
        #approval-overlay .ao-collapse-btn:hover { color: #e8f2ed; }
      </style>
      <div id="ao-content"></div>
    `;
    document.body.appendChild(el);
    return el;
  }

  // --- Rendering ---

  function render() {
    const container = document.getElementById("ao-content");
    if (!container) return;

    if (items.length === 0) {
      container.innerHTML = `<div class="ao-badge ao-clear" id="ao-clear-badge">✓ All clear</div>`;
      setTimeout(() => {
        const badge = document.getElementById("ao-clear-badge");
        if (badge) badge.classList.add("ao-fade");
      }, FADE_DELAY);
      return;
    }

    // Clamp index
    if (currentIndex >= items.length) currentIndex = 0;
    const item = items[currentIndex];

    let thumbHtml = "";
    if (item.screenshot_url) {
      thumbHtml = `<img class="ao-thumb" src="/api/approvals/screenshot/${item.screenshot_url}" alt="Preview">`;
    } else if (item.diff_url) {
      thumbHtml = `<img class="ao-thumb" src="/api/approvals/screenshot/${item.diff_url}" alt="Diff">`;
    }

    container.innerHTML = `
      <div class="ao-card">
        <div class="ao-card-header">
          <span>Pending approval</span>
          <span class="ao-counter">${currentIndex + 1} of ${items.length}</span>
          <button class="ao-collapse-btn" onclick="window._aoCollapse()" title="Minimize">−</button>
        </div>
        <div class="ao-card-body">
          <p class="ao-title">${escapeHtml(item.title)}</p>
          ${thumbHtml}
          <p class="ao-desc">${escapeHtml(item.description)}</p>
        </div>
        <div class="ao-actions">
          <button class="ao-btn ao-approve" onclick="window._aoVerdict('${item.id}', true)">👍 Approve</button>
          <button class="ao-btn ao-reject" onclick="window._aoVerdict('${item.id}', false)">👎 Reject</button>
        </div>
      </div>
    `;
  }

  function renderCollapsed() {
    const container = document.getElementById("ao-content");
    if (!container) return;
    const count = items.length;
    container.innerHTML = `<div class="ao-badge" onclick="window._aoExpand()">${count} pending</div>`;
  }

  let expanded = true;

  window._aoCollapse = function() {
    expanded = false;
    renderCollapsed();
  };

  window._aoExpand = function() {
    expanded = true;
    render();
  };

  // --- API Interaction ---

  async function fetchPending() {
    try {
      const resp = await fetch("/api/approvals");
      if (!resp.ok) return;
      items = await resp.json();
      if (expanded) {
        render();
      } else if (items.length > 0) {
        renderCollapsed();
      } else {
        expanded = true;
        render();
      }
    } catch (e) {
      // Silently fail polling — don't disrupt the main UI
    }
  }

  window._aoVerdict = async function(itemId, approved) {
    const endpoint = approved ? "approve" : "reject";
    try {
      const resp = await fetch(`/api/approvals/${itemId}/${endpoint}`, { method: "POST" });
      if (!resp.ok) return;
      // Remove from local list and advance
      items = items.filter(i => i.id !== itemId);
      if (currentIndex >= items.length) currentIndex = 0;
      render();
    } catch (e) {
      // Silent failure
    }
  };

  // --- Utilities ---

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  // --- Init ---

  function init() {
    overlay = createOverlay();
    fetchPending();
    pollTimer = setInterval(fetchPending, POLL_INTERVAL);
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
