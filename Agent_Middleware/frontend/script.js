/* ── TalkBuddy — script.js ─────────────────────────────────── */

const WS_URL     = "ws://localhost:8000/ws";
const MIC_WS_URL = "ws://localhost:8000/ws/mic";
const API_URL    = "http://localhost:8000";

// ── DOM refs ──────────────────────────────────────────────────
const chat          = document.getElementById("chat");
const msgInput      = document.getElementById("msgInput");
const connBadge     = document.getElementById("connBadge");
const wsDot         = document.getElementById("wsStatus");
const waveBar       = document.getElementById("waveformBar");
const micBtn        = document.getElementById("micBtn");
const waveCanvas    = document.getElementById("waveCanvas");
const micTimer      = document.getElementById("micTimer");
const mcpPanel      = document.getElementById("mcpPanel");
const mcpTools      = document.getElementById("mcpTools");
const activePills   = document.getElementById("activePills");
const appShell      = document.getElementById("appShell");
const chatContainer = document.getElementById("chatContainer");
const attMenu       = document.getElementById("attMenu");
const historyList   = document.getElementById("historyList");
const pdfStoreList  = document.getElementById("pdfStoreList");
const pdfCountBadge = document.getElementById("pdfCountBadge");

// ── PDF Store State ───────────────────────────────────────────
// storedPdfs: [{pdf_id, filename, page_count, uploaded_at}]
let storedPdfs    = [];
// activePdfIds: set of pdf_ids selected for Q&A (empty = all)
let activePdfIds  = new Set();

// ── Session History ───────────────────────────────────────────
let sessions      = [];
let activeSession = null;

function _makeSession(title) {
  return { id: Date.now(), title, messages: [] };
}
function _saveCurrentToHistory() {
  if (!activeSession || activeSession.messages.length === 0) return;
  const idx = sessions.findIndex(s => s.id === activeSession.id);
  if (idx >= 0) sessions[idx] = activeSession;
  else sessions.unshift(activeSession);
  renderHistory();
}
function renderHistory() {
  const today = new Date().toDateString();
  const todayItems  = sessions.filter(s => new Date(s.id).toDateString() === today);
  const olderItems  = sessions.filter(s => new Date(s.id).toDateString() !== today);
  let html = "";
  if (todayItems.length) {
    html += `<div class="history-label">Today</div>`;
    todayItems.forEach(s => {
      html += `<div class="history-item${activeSession?.id === s.id ? " active-session" : ""}"
                    onclick="loadSession(${s.id})" title="${escHtml(s.title)}">
                 ${escHtml(s.title.length > 32 ? s.title.slice(0, 32) + "…" : s.title)}
               </div>`;
    });
  }
  if (olderItems.length) {
    html += `<div class="history-label" style="margin-top:14px">Earlier</div>`;
    olderItems.forEach(s => {
      html += `<div class="history-item${activeSession?.id === s.id ? " active-session" : ""}"
                    onclick="loadSession(${s.id})" title="${escHtml(s.title)}">
                 ${escHtml(s.title.length > 32 ? s.title.slice(0, 32) + "…" : s.title)}
               </div>`;
    });
  }
  if (!sessions.length) {
    html = `<div style="font-size:12px;color:#4b5563;padding:12px 0">No history yet</div>`;
  }
  historyList.innerHTML = html;
}
function loadSession(id) {
  _saveCurrentToHistory();
  const session = sessions.find(s => s.id === id);
  if (!session) return;
  activeSession = session;
  chat.innerHTML = "";
  session.messages.forEach(m => {
    const el = document.createElement("div");
    el.className = "msg " + m.role;
    el.innerHTML = m.html;
    chat.appendChild(el);
  });
  startChat(); scrollBottom(); renderHistory();
}

// ── UI State ──────────────────────────────────────────────────
function toggleSidebar()       { appShell.classList.toggle("sidebar-open"); }
function toggleAttachmentMenu(){ attMenu.classList.toggle("open"); }

function startChat() {
  chatContainer.classList.remove("chat-empty");
  if (!activeSession) activeSession = _makeSession("New Chat");
}
function newChat() {
  _saveCurrentToHistory();
  activeSession = null;
  chat.innerHTML = "";
  clearActivePdfs();
  chatContainer.classList.add("chat-empty");
  msgInput.placeholder = "Message the agents…";
  activePills.innerHTML = "";
  renderHistory();
}
document.addEventListener("click", (e) => {
  const wrapper = document.getElementById("attachmentWrapper");
  if (wrapper && !wrapper.contains(e.target)) attMenu.classList.remove("open");
});

// ── WebSocket ─────────────────────────────────────────────────
let ws;
let wsManualDisconnect = false;  // true = user clicked Disconnect, skip auto-reconnect
let wsReconnectTimer   = null;

function connectWS() {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
  setConnState("connecting");
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsManualDisconnect = false;
    setConnState("ok");
  };

  ws.onmessage = (evt) => {
    removeTyping();
    const data = JSON.parse(evt.data);
    const waitMsg = document.getElementById("hitlWaitMsg");
    if (waitMsg && data.type !== "hitl_wait") {
      waitMsg.remove();
    }

    if      (data.type === "hitl_answer")  renderHitlAnswer(data);
    else if (data.type === "hitl_timeout") addBotMessage(data.chat || data.answer);
    else if (data.type === "hitl_wait") {
      const el = document.createElement("div");
      el.className = "msg bot hitl-wait-msg";
      el.id = "hitlWaitMsg";
      el.innerHTML = `<div class="msg-bubble">${escHtml(data.message)}</div>`;
      chat.appendChild(el);
      scrollBottom();
    }
    else if (data.type === "pdf_answer")   renderMultiPdfAnswer(data);
    else                                   renderBotResponse(data);
  };

  ws.onclose = () => {
    setConnState("err");
    // Only auto-reconnect when disconnection was NOT triggered by the user
    if (!wsManualDisconnect) {
      wsReconnectTimer = setTimeout(connectWS, 2500);
    }
  };

  ws.onerror = () => setConnState("err");
}

// Connect button handler
function manualConnect() {
  wsManualDisconnect = false;
  connectWS();
}

// Disconnect button handler — sends clean close frame (code 1000) to FastAPI
function manualDisconnect() {
  wsManualDisconnect = true;
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close(1000, "User disconnected");   // triggers WebSocketDisconnect on backend
  }
  setConnState("err");
}

connectWS();  // auto-connect on page load

function setConnState(s) {
  const btnConnect    = document.getElementById("wsBtnConnect");
  const btnDisconnect = document.getElementById("wsBtnDisconnect");

  connBadge.textContent = "●";

  if (s === "ok") {
    connBadge.className = "conn-badge ok";
    wsDot.className     = "status-dot connected";
    if (btnConnect)    btnConnect.style.display    = "none";
    if (btnDisconnect) btnDisconnect.style.display = "flex";
  } else if (s === "connecting") {
    connBadge.className = "conn-badge connecting";
    wsDot.className     = "status-dot";
    if (btnConnect)    btnConnect.style.display    = "flex";
    if (btnDisconnect) btnDisconnect.style.display = "none";
  } else {
    // err / disconnected
    connBadge.className = "conn-badge err";
    wsDot.className     = "status-dot error";
    if (btnConnect)    btnConnect.style.display    = "flex";
    if (btnDisconnect) btnDisconnect.style.display = "none";
  }
}

function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;
  msgInput.value = "";
  startChat();

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addBotMessage("⚠ Not connected. Please wait…"); return;
  }
  
  addUserMessage(text);
  showTyping();

  const ids = activePdfIds.size > 0 ? Array.from(activePdfIds) : null;
  ws.send(JSON.stringify({ 
    type: "query", 
    text: text,
    has_pdfs: storedPdfs.length > 0,
    pdf_ids: ids 
  }));
}
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

async function fetchStoredPdfs() {
  try {
    const res  = await fetch(`${API_URL}/pdfs`);
    const data = await res.json();
    storedPdfs = data.pdfs || [];
    renderPdfStore();
  } catch (e) {
    console.warn("[PDFStore] Could not fetch:", e.message);
  }
}

// ── Render PDF library in sidebar ────────────────────────────
function renderPdfStore() {
  pdfCountBadge.textContent = storedPdfs.length;

  if (!storedPdfs.length) {
    pdfStoreList.innerHTML = `<div class="pdf-store-empty">No PDFs uploaded</div>`;
    return;
  }

  pdfStoreList.innerHTML = storedPdfs.map(pdf => {
    const isActive = activePdfIds.has(pdf.pdf_id);
    const date     = new Date(pdf.uploaded_at).toLocaleDateString(undefined, { month:"short", day:"numeric" });
    return `
      <div class="pdf-store-item ${isActive ? "pdf-selected" : ""}" id="pdfItem_${pdf.pdf_id}">
        <div class="pdf-item-info" onclick="togglePdfSelection('${pdf.pdf_id}')" title="Click to include/exclude from Q&A">
          <div class="pdf-item-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
          </div>
          <div class="pdf-item-meta">
            <div class="pdf-item-name">${escHtml(pdf.filename)}</div>
            <div class="pdf-item-stats">${pdf.page_count} pages · ${date}</div>
          </div>
          ${isActive ? `<div class="pdf-item-check">✓</div>` : ""}
        </div>
        <div class="pdf-item-actions">
          <button class="pdf-action-btn pdf-del-btn" onclick="deletePdf('${pdf.pdf_id}', '${escHtml(pdf.filename)}')" title="Delete PDF">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6M10 11v6M14 11v6M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>`;
  }).join("");

}

// ── Toggle a PDF in/out of active selection ───────────────────
function togglePdfSelection(pdfId) {
  if (activePdfIds.has(pdfId)) activePdfIds.delete(pdfId);
  else activePdfIds.add(pdfId);
  renderPdfStore();
}

function clearActivePdfs() {
  activePdfIds.clear();
  renderPdfStore();
  if (!storedPdfs.length) {
    msgInput.placeholder = "Message the agents…";
  }
}

// ── Upload one or many PDFs ───────────────────────────────────
async function uploadPdfs(files) {
  if (!files || files.length === 0) return;
  startChat();
  attMenu.classList.remove("open");

  const names = Array.from(files).map(f => f.name).join(", ");
  showTyping();

  try {
    let uploaded = [];

    if (files.length === 1) {
      // single: use /upload-pdf
      const fd = new FormData();
      fd.append("file", files[0]);
      fd.append("question", "");
      const res  = await fetch(`${API_URL}/upload-pdf`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`Server ${res.status}: ${await res.text()}`);
      const data = await res.json();
      uploaded.push(data);
    } else {
      // multi: use /upload-pdfs
      const fd = new FormData();
      Array.from(files).forEach(f => fd.append("files", f));
      const res  = await fetch(`${API_URL}/upload-pdfs`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`Server ${res.status}: ${await res.text()}`);
      const data = await res.json();
      uploaded = data.pdfs || [];
    }

    removeTyping();

    // refresh store
    await fetchStoredPdfs();

    // chat confirmation with page counts
    const summary = uploaded.map(d =>
      ` **${d.filename}** — ${d.page_count} pages indexed`
    ).join("\n");

  } catch (err) {
    removeTyping();
    addBotMessage(`⚠ PDF upload failed: ${err.message}`);
  }
}

// Hook both upload inputs (attachment menu + sidebar add button)
document.getElementById("pdfFile").addEventListener("change", function () {
  if (this.files.length) { uploadPdfs(this.files); this.value = ""; }
});
document.getElementById("pdfStoreFile").addEventListener("change", function () {
  if (this.files.length) { uploadPdfs(this.files); this.value = ""; }
});

// ── Delete a PDF ──────────────────────────────────────────────
async function deletePdf(pdfId, filename) {
  if (!confirm(`Delete "${filename}"?\n\nThis removes the file and clears all cached answers for it.`)) return;

    const res = await fetch(`${API_URL}/pdfs/${pdfId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Server ${res.status}: ${await res.text()}`);
    const data = await res.json();

    // remove from local state
    storedPdfs   = storedPdfs.filter(p => p.pdf_id !== pdfId);
    activePdfIds.delete(pdfId);
    renderPdfStore();
}


// ── Ask about a specific page ────────────────────────────────
function askAboutPage(pdfId, pageNum, filename) {
  msgInput.value = `What is on page ${pageNum} of ${filename}?`;
  activePdfIds.clear();
  activePdfIds.add(pdfId);
  renderPdfStore();
  msgInput.focus();
}

// ── Render multi-PDF answer with source cards ─────────────────
function renderMultiPdfAnswer(data) {
  const answer  = data.answer || data.chat || "(no response)";
  const sources = data.sources || [];
  const cached  = data.from_cache;

  // dedupe sources by pdf_id+page
  const seen = new Set();
  const uniqueSources = sources.filter(s => {
    const k = `${s.pdf_id}:${s.page}`;
    if (seen.has(k)) return false;
    seen.add(k); return true;
  });

  const sourceCards = uniqueSources.map(s => `
    <div class="source-card" onclick="askAboutPage('${s.pdf_id}', ${s.page}, '${escHtml(s.filename)}')">
      <div class="source-card-file">${escHtml(s.filename)}</div>
      <div class="source-card-page">Page ${s.page}</div>
      <div class="source-card-score">${Math.round(s.score * 100)}%</div>
    </div>`).join("");

  const innerHtml = `
    <div class="msg-bubble">${formatResponse(answer)}</div>
    ${uniqueSources.length ? `<div class="multi-source-row">
      </div>` : ""}`;

  _appendMsg("bot", innerHtml);
}

// ═══════════════════════════════════════════════════════════════
//  Render helpers
// ═══════════════════════════════════════════════════════════════

function addUserMessage(text) {
  const innerHtml = `<div class="msg-bubble">${escHtml(text)}</div>`;
  if (activeSession && activeSession.messages.filter(m => m.role === "user").length === 0) {
    activeSession.title = text.length > 40 ? text.slice(0, 40) + "…" : text;
  }
  _appendMsg("user", innerHtml);
}

function addBotMessage(text) {
  const innerHtml = `<div class="msg-bubble">${formatResponse(text)}</div>`;
  _appendMsg("bot", innerHtml);
}

function renderBotResponse(data) {
  const tags = [];
  if (data.from_cache)           tags.push({ cls: "cache", label: "Cached — 0 tokens used" });
  if (data.mcp)                  tags.push({ cls: "mcp",   label: "MCP" });
  if (data.results?.code)        tags.push({ cls: "code",  label: "Code" });
  if (data.results?.research)    tags.push({ cls: "",      label: "Research" });
  updatePills(data.results || {});
  addBotMessage(data.chat || data.answer || "(no response)");
  fetchCostSavings();
}

function _appendMsg(role, innerHtml) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.innerHTML = innerHtml;
  chat.appendChild(el);
  scrollBottom();
  if (activeSession) {
    activeSession.messages.push({ role, html: innerHtml });
    _saveCurrentToHistory();
  }
}

function updatePills(results) {
  activePills.innerHTML = Object.keys(results)
    .map(a => `<span class="pill active">${a}</span>`).join("");
}

function showTyping() {
  if (document.getElementById("typingIndicator")) return;
  const el = document.createElement("div");
  el.className = "msg bot typing-indicator";
  el.id = "typingIndicator";
  el.innerHTML = `<div class="msg-bubble"><div class="dots"><span/><span/><span/></div></div>`;
  chat.appendChild(el); scrollBottom();
}
function removeTyping() { document.getElementById("typingIndicator")?.remove(); }
function scrollBottom()  { chat.scrollTop = chat.scrollHeight; }

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Configure marked.js for clean rendering
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false,
});

function formatResponse(text) {
  try {
    return marked.parse(String(text));
  } catch (e) {
    return escHtml(text).replace(/\n/g, "<br>");
  }
}

// ── Audio / Video upload ──────────────────────────────────────
document.getElementById("audioFile").addEventListener("change", async function () {
  const file = this.files[0]; if (!file) return; this.value = "";
  startChat(); attMenu.classList.remove("open");
  addUserMessage(`🎵 ${file.name}`, [{ cls: "", label: "Audio" }]); showTyping();
  const fd = new FormData(); fd.append("file", file);
  try {
    const data = await (await fetch(`${API_URL}/upload-audio`, { method: "POST", body: fd })).json();
    removeTyping();
    addUserMessage(data.transcript, [{ cls: "mic", label: "Transcribed" }]);
    renderBotResponse(data);
  } catch (err) { removeTyping(); addBotMessage("⚠ Audio failed: " + err.message); }
});

document.getElementById("videoFile").addEventListener("change", async function () {
  const file = this.files[0]; if (!file) return; this.value = "";
  startChat(); attMenu.classList.remove("open");
  addUserMessage(`🎬 ${file.name}`, [{ cls: "", label: "Video" }]); showTyping();
  const fd = new FormData(); fd.append("file", file);
  try {
    const data = await (await fetch(`${API_URL}/upload-video`, { method: "POST", body: fd })).json();
    removeTyping();
    addUserMessage(data.transcript, [{ cls: "mic", label: "Transcribed" }]);
    renderBotResponse(data);
  } catch (err) { removeTyping(); addBotMessage("⚠ Video failed: " + err.message); }
});

// ── Mic ───────────────────────────────────────────────────────
let mediaRecorder = null, micWs = null, audioChunks = [];
let timerInterval = null, timerSec = 0;
let analyser = null, animFrame = null, audioCtx = null;

async function toggleMic() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") stopMic();
  else await startMic();
}
async function startMic() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioCtx = new AudioContext();
    const src = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser(); analyser.fftSize = 256;
    src.connect(analyser); drawWave();

    micWs = new WebSocket(MIC_WS_URL);
    micWs.binaryType = "arraybuffer";
    micWs.onmessage = (evt) => {
      const data = JSON.parse(evt.data); removeTyping();
      if (data.type === "transcript") {
        addUserMessage(data.text, [{ cls: "mic", label: "Transcribed" }]); showTyping();
      } else if (data.type === "agent_result") {
        renderBotResponse(data);
        if (micWs) { micWs.close(); micWs = null; }
      }
    };
    micWs.onclose = () => removeTyping();
    micWs.onerror = () => { removeTyping(); addBotMessage("⚠ Mic connection error"); };

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, { type: "audio/webm" }); audioChunks = [];
      startChat();
      if (micWs?.readyState === WebSocket.OPEN) {
        showTyping(); micWs.send(await blob.arrayBuffer());
      }
      stream.getTracks().forEach(t => t.stop());
    };
    mediaRecorder.start();
    micBtn.classList.add("active"); waveBar.classList.add("active");
    timerSec = 0; micTimer.textContent = "0:00";
    timerInterval = setInterval(() => {
      timerSec++;
      micTimer.textContent = `${Math.floor(timerSec/60)}:${String(timerSec%60).padStart(2,"0")}`;
    }, 1000);
  } catch (err) { alert("Microphone error: " + err.message); }
}
function stopMic() {
  if (mediaRecorder?.state !== "inactive") mediaRecorder?.stop();
  clearInterval(timerInterval); cancelAnimationFrame(animFrame);
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  micBtn.classList.remove("active"); waveBar.classList.remove("active");
}
function drawWave() {
  const ctx = waveCanvas.getContext("2d");
  const buf = new Uint8Array(analyser.frequencyBinCount);
  const W = waveCanvas.width, H = waveCanvas.height;
  function render() {
    animFrame = requestAnimationFrame(render);
    analyser.getByteTimeDomainData(buf);
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "#f5495b"; ctx.lineWidth = 2; ctx.beginPath();
    buf.forEach((v, i) => {
      const x = i * W / buf.length, y = (v / 128) * H / 2;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(W, H/2); ctx.stroke();
  }
  render();
}

// ── MCP Panel ─────────────────────────────────────────────────
function toggleMcpPanel() { if (mcpPanel.classList.toggle("open")) loadMcpTools(); }
async function loadMcpTools() {
  mcpTools.innerHTML = "Loading…";
  try {
    const data = await (await fetch(`${API_URL.replace("8000","8001")}/mcp/tools`)).json();
    const tools = data.tools || {};
    mcpTools.innerHTML = Object.keys(tools).length
      ? Object.entries(tools).map(([n,i]) => `
          <div class="mcp-tool-card">
            <div class="mcp-tool-name">${n}</div>
            <div class="mcp-tool-desc">${i.description}</div>
            <div class="mcp-provider">${i.provider}</div>
          </div>`).join("")
      : `<span style="color:#4b5563;font-size:12px">No tools registered</span>`;
  } catch {
    mcpTools.innerHTML = `<span style="color:var(--red);font-size:12px">MCP server unreachable</span>`;
  }
}

// ── Init ──────────────────────────────────────────────────────
renderHistory();
fetchStoredPdfs();   // load existing PDFs from server on startup

// ── Cost Savings ──────────────────────────────────────────────
async function fetchCostSavings() {
  try {
    const res = await fetch(`${API_URL}/stats/cost-savings`);
    const data = await res.json();
    
    const hits   = data.cache_hits   || 0;
    const misses = data.cache_misses || 0;
    const total  = hits + misses;
    const hitPct = total > 0 ? Math.round((hits / total) * 100) : 0;

    // Cache Miss card
    document.getElementById("statMisses").textContent    = misses;
    document.getElementById("statTokensUsed").textContent = (data.used_input_tokens || 0) + (data.used_output_tokens || 0);
    document.getElementById("statCostUsed").textContent  = "$" + (data.used_cost_usd || 0).toFixed(4);

    // Cache Hit card
    document.getElementById("statHits").textContent   = hits;
    document.getElementById("statTokens").textContent = (data.saved_input_tokens || 0) + (data.saved_output_tokens || 0);
    document.getElementById("statCost").textContent   = "$" + (data.cost_saved_usd || 0).toFixed(4);

    // Summary bar
    const totalEl   = document.getElementById("statTotal");
    const barEl     = document.getElementById("statHitBar");
    const rateEl    = document.getElementById("statHitRate");
    if (totalEl)  totalEl.textContent  = total;
    if (barEl)    barEl.style.width    = hitPct + "%";
    if (rateEl)   rateEl.textContent   = hitPct + "% hit rate";

  } catch (e) {
    console.warn("Could not fetch cost savings:", e);
  }
}
// ── App Views Navigation ────────────────────────────────────────
function switchView(viewName) {
  // Hide all views
  document.querySelectorAll('.app-view').forEach(view => {
    view.classList.remove('active');
    view.style.display = 'none'; // Ensure inline hidden if needed
  });
  
  // Show target
  const target = document.getElementById('view' + viewName.charAt(0).toUpperCase() + viewName.slice(1));
  if (target) {
    target.classList.add('active');
    target.style.display = 'flex';
  }
  
  // Update nav inactive/active state
  document.querySelectorAll('.sidebar-nav .nav-tab').forEach(btn => {
    btn.classList.remove('active');
    if (btn.getAttribute('onclick').includes(viewName)) {
      btn.classList.add('active');
    }
  });

  // On mobile, close sidebar on nav click
  if (window.innerWidth <= 768) {
    toggleSidebar();
  }
}

fetchCostSavings(); // initial load

// ── Clear All Cache ────────────────────────────────────────────
async function clearAllCache() {
  const btn = document.getElementById("clearCacheBtn");
  const originalText = btn.innerHTML;

  // Visual feedback during clearing
  btn.disabled = true;
  btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" style="animation: spin 0.8s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Clearing…`;
  btn.style.opacity = "0.6";

  try {
    const res = await fetch(`${API_URL}/cache/clear-all`, { method: "POST" });
    const data = await res.json();

    if (data.status === "cleared") {
      // Flash green briefly
      btn.style.color = "#10b981";
      btn.style.borderColor = "#10b981";
      btn.innerHTML = `✓ Cleared ${data.cache_keys_deleted} keys`;
      await fetchCostSavings(); // refresh stats to zero

      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.style.color = "#f5495b";
        btn.style.borderColor = "#f5495b55";
        btn.disabled = false;
        btn.style.opacity = "1";
      }, 2000);
    }
  } catch (e) {
    console.error("Clear cache failed:", e);
    btn.innerHTML = "✕ Failed";
    btn.style.color = "#f5495b";
    setTimeout(() => {
      btn.innerHTML = originalText;
      btn.disabled = false;
      btn.style.opacity = "1";
    }, 2000);
  }
}

const _style = document.createElement("style");
_style.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(_style);


// ── Render the final HITL answer ─────────────────────────────
function renderHitlAnswer(data) {
  const answer  = data.answer || data.chat || "(no response)";

  const html = `
    <div class="msg-bubble hitl-answer-bubble">
      ${formatResponse(answer)}
    </div>`;

  _appendMsg("bot", html);
}