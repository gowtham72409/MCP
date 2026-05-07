const API_URL = "http://localhost:8000";
const queueList = document.getElementById("queueList");
const queueCount = document.getElementById("queueCount");
const connStatus = document.getElementById("connStatus");
const statusDot = document.querySelector(".status-dot");

let currentReviews = [];

const WS_URL = "ws://localhost:8000/admin/ws";

function connectAdminWS() {
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    statusDot.className = "status-dot connected";
    connStatus.textContent = "Live Queue (Connected)";
  };

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      const newReviewsStr = JSON.stringify(data.reviews.map(r => r.review_id));
      const oldReviewsStr = JSON.stringify(currentReviews.map(r => r.review_id));
      
      if (newReviewsStr !== oldReviewsStr) {
        currentReviews = data.reviews || [];
        renderQueue();
      }
    } catch (err) {
      console.error("WS parse error:", err);
    }
  };

  ws.onclose = () => {
    statusDot.className = "status-dot";
    connStatus.textContent = "Reconnecting...";
    setTimeout(connectAdminWS, 3000);
  };
}

function renderQueue() {
  queueCount.textContent = currentReviews.length;
  
  if (currentReviews.length === 0) {
    queueList.innerHTML = `<div class="empty-state">No pending reviews.</div>`;
    return;
  }

  queueList.innerHTML = currentReviews.map(rev => {
    const time = new Date(rev.created_at * 1000).toLocaleTimeString();
    return `
      <div class="review-card" id="card_${rev.review_id}">
        <div class="review-header">
          <span style="font-weight: 600; font-size: 14px;">Sensitive Query Detected</span>
          <span class="review-time">${time}</span>
        </div>
        <div class="review-body">
          <div class="review-section">
            <div class="section-label">User Question</div>
            <div class="question-text">${escapeHtml(rev.question)}</div>
          </div>
          <div class="review-section">
            <div class="section-label">Draft Answer</div>
            <textarea class="answer-editor" id="draft_${rev.review_id}">${escapeHtml(rev.draft_answer)}</textarea>
          </div>
        </div>
        <div class="review-actions">
          <button class="btn btn-reject" onclick="submitAction('${rev.review_id}', 'reject')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Reject
          </button>
          <button class="btn btn-edit" onclick="submitAction('${rev.review_id}', 'edit')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            Edit & Send
          </button>
          <button class="btn btn-approve" onclick="submitAction('${rev.review_id}', 'approve')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="20 6 9 17 4 12"/></svg>
            Approve Default
          </button>
        </div>
      </div>
    `;
  }).join("");
}

async function submitAction(reviewId, action) {
  const card = document.getElementById(`card_${reviewId}`);
  if (card) {
    card.style.opacity = "0.5";
    card.style.pointerEvents = "none";
  }

  const draftEl = document.getElementById(`draft_${reviewId}`);
  const edited_answer = draftEl ? draftEl.value : "";

  try {
    const res = await fetch(`${API_URL}/admin/reviews/${reviewId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, edited_answer })
    });

    if (!res.ok) throw new Error("Submission failed");
    
    // Re-render queue instantly locally to hide the card
    currentReviews = currentReviews.filter(r => r.review_id !== reviewId);
    renderQueue();
  } catch (err) {
    console.error(err);
    alert("Failed to submit action: " + err.message);
    if (card) {
      card.style.opacity = "1";
      card.style.pointerEvents = "auto";
    }
  }
}

function escapeHtml(unsafe) {
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Connect on load
connectAdminWS();
