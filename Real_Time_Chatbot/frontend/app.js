const API = 'http://localhost:8000/api';
const WS_URL = 'ws://localhost:8000/api/chat/ws';

let state = {
  agents: [],
  currentAgent: null,
  currentConvId: null,
  isStreaming: false,
  workflowEnabled: false,
  wsClient: null,
  clientId: 'client_' + Math.random().toString(36).slice(2),
  metrics: { messages: 0, tokens: 0, avgTime: 0 },
  intentData: null,
  editingAgent: null,
};

// ===== INIT =====
async function init() {
  await loadAgents();
  await loadSkills();
  checkApiKey();
  initWebSocket();
  setupIntentDebounce();
}

async function checkApiKey() {
  try {
    const r = await fetch(`${API}/system/settings`);
    const d = await r.json();
    document.getElementById('apiBanner').style.display = d.api_key_configured ? 'none' : 'flex';
  } catch {}
}

function initWebSocket() {
  state.wsClient = new WebSocket(`${WS_URL}/${state.clientId}`);
  
  state.wsClient.onopen = () => {
    document.getElementById('wsDot').classList.add('connected');
    document.getElementById('wsLabel').textContent = 'Connected';
    setInterval(() => {
      if (state.wsClient?.readyState === 1) state.wsClient.send(JSON.stringify({type: 'ping'}));
    }, 30000);
  };
  
  state.wsClient.onclose = () => {
    document.getElementById('wsDot').classList.remove('connected');
    document.getElementById('wsLabel').textContent = 'Disconnected';
    setTimeout(initWebSocket, 3000);
  };
}

// ===== AGENTS =====
async function loadAgents() {
  try {
    const r = await fetch(`${API}/agents`);
    state.agents = await r.json();
    renderAgents();
  } catch (e) {
    console.error('Failed to load agents:', e);
  }
}

function renderAgents() {
  const el = document.getElementById('agentList');
  if (!state.agents.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px;text-align:center;padding:16px">No agents found</div>';
    return;
  }
  el.innerHTML = state.agents.map(a => `
    <div class="agent-card ${state.currentAgent?.id === a.id ? 'active' : ''}" onclick="selectAgent('${a.id}')">
      <div class="agent-card-header">
        <div class="agent-name">${escHtml(a.name)}</div>
        <button class="agent-delete-btn" onclick="deleteAgent(event, '${a.id}')" title="Delete agent">×</button>
      </div>
      <div class="agent-desc">${escHtml(a.description || '')}</div>
      <div class="agent-model">${a.model || ''}</div>
      <div class="agent-skills">
        ${(a.skills || []).slice(0, 3).map(s => `<span class="skill-badge">${s}</span>`).join('')}
        ${(a.skills || []).length > 3 ? `<span class="skill-badge">+${a.skills.length - 3}</span>` : ''}
      </div>
    </div>
  `).join('');
}

async function selectAgent(id) {
  state.currentAgent = state.agents.find(a => a.id === id);
  if (!state.currentAgent) return;
  
  state.currentConvId = null;
  document.getElementById('chatAgentName').textContent = state.currentAgent.name;
  document.getElementById('chatAgentAvatar').textContent = getAgentEmoji(state.currentAgent);
  document.getElementById('statusDot').style.background = 'var(--accent3)';
  document.getElementById('statusText').textContent = 'Ready';
  document.getElementById('sendBtn').disabled = false;
  document.getElementById('editAgentBtn').style.display = 'flex';
  
  renderAgents();
  clearChat();
  await loadConversations();
}

function getAgentEmoji(agent) {
  const emojis = { 'Code': '', 'Research': '', 'General': '', 'Data': '', 'Creative': '' };
  for (const [k, e] of Object.entries(emojis)) {
    if (agent.name.includes(k)) return e;
  }
  return '';
}

async function deleteAgent(e, id) {
  e.stopPropagation();
  const agent = state.agents.find(a => a.id === id);
  if (!confirm(`Delete agent "${agent?.name || id}"?`)) return;
  try {
    const r = await fetch(`${API}/agents/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error('Failed to delete');
    toast('Agent deleted', 'success');
    if (state.currentAgent?.id === id) {
      state.currentAgent = null;
      state.currentConvId = null;
      document.getElementById('chatAgentName').textContent = 'Select an Agent';
      document.getElementById('sendBtn').disabled = true;
      document.getElementById('editAgentBtn').style.display = 'none';
      clearMessages();
    }
    await loadAgents();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function loadConversations() {
  if (!state.currentAgent) return;
  try {
    const r = await fetch(`${API}/agents/${state.currentAgent.id}/conversations`);
    const convs = await r.json();
    const el = document.getElementById('convList');
    if (!convs.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:12px;text-align:center;padding:16px">No conversations yet</div>';
      return;
    }
    el.innerHTML = convs.map(c => `
      <div class="conv-item ${state.currentConvId === c.id ? 'active' : ''}" onclick="loadConversation(${c.id})">
        <div class="conv-dot"></div>
        <div class="conv-title">${escHtml(c.title)}</div>
        <button class="conv-delete" onclick="deleteConversation(event, ${c.id})">×</button>
      </div>
    `).join('');
  } catch {}
}

async function loadConversation(id) {
  try {
    const r = await fetch(`${API}/chat/conversations/${id}`);
    const data = await r.json();
    state.currentConvId = id;
    
    clearMessages();
    for (const msg of data.messages) {
      if (msg.role === 'user') {
        appendUserMessage(msg.content);
      } else {
        appendAssistantMessage(msg.content, msg.thought_process, msg.tool_calls || []);
      }
    }
    await loadConversations();
  } catch (e) {
    toast('Failed to load conversation', 'error');
  }
}

async function deleteConversation(e, id) {
  e.stopPropagation();
  if (!confirm('Delete this conversation?')) return;
  await fetch(`${API}/chat/conversations/${id}`, {method: 'DELETE'});
  if (state.currentConvId === id) {
    state.currentConvId = null;
    clearMessages();
  }
  await loadConversations();
  toast('Conversation deleted', 'success');
}

// ===== SKILLS =====
async function loadSkills() {
  try {
    const r = await fetch(`${API}/skills`);
    const skills = await r.json();
    renderSkills(skills);
    
    // Update skill checkboxes in agent modal
    const cont = document.getElementById('skillsCheckboxes');
    cont.innerHTML = skills.map(s => `
      <label class="skill-check">
        <input type="checkbox" value="${s.name}" class="skill-checkbox">
        <span>${s.name}</span>
      </label>
    `).join('');
  } catch {}
}

function renderSkills(skills) {
  const el = document.getElementById('skillList');
  el.innerHTML = skills.map(s => `
    <div class="skill-item">
      <div class="skill-name">${s.name}</div>
      <div class="skill-desc">${s.description || '–'}</div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px">
        <div class="skill-source">${s.source || 'builtin'}</div>
        ${s.source === 'custom' ? `<button onclick="deleteSkill('${s.name}')" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:11px">× remove</button>` : ''}
      </div>
    </div>
  `).join('');
}

async function uploadSkill() {
  const name = document.getElementById('skillName').value.trim();
  const desc = document.getElementById('skillDesc').value.trim();
  const code = document.getElementById('skillCode').value.trim();
  const file = document.getElementById('skillFile').files[0];

  if (file) {
    // File upload
    const form = new FormData();
    form.append('file', file);
    try {
      const r = await fetch(`${API}/skills/upload`, {method: 'POST', body: form});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      toast(`Skill "${d.name}" loaded!`, 'success');
      closeModal('skillModal');
      await loadSkills();
    } catch (e) {
      toast(e.message, 'error');
    }
    return;
  }

  if (!name || !code) return toast('Name and code required', 'error');
  if (!code.includes('def execute')) return toast('Code must have an execute() function', 'error');
  
  try {
    const r = await fetch(`${API}/skills`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, description: desc, code, parameters: {}}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail);
    toast(`Skill "${name}" loaded dynamically!`, 'success');
    closeModal('skillModal');
    await loadSkills();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function deleteSkill(name) {
  await fetch(`${API}/skills/${name}`, {method: 'DELETE'});
  toast(`Skill "${name}" unloaded`, 'info');
  await loadSkills();
}

// ===== CHAT =====
let intentTimeout = null;
function setupIntentDebounce() {}

async function detectIntent(text) {
  clearTimeout(intentTimeout);
  if (!text.trim() || text.length < 5) return;
  intentTimeout = setTimeout(async () => {
    // Just show placeholder intent detection locally
    const keywords = {
      question: ['what', 'how', 'why', 'when', 'where', 'who', '?'],
      code: ['code', 'function', 'debug', 'error', 'python', 'javascript', 'class'],
      analysis: ['analyze', 'compare', 'evaluate', 'assess', 'review'],
      creative: ['write', 'create', 'generate', 'imagine', 'story', 'poem'],
      task: ['do', 'make', 'build', 'create', 'implement', 'calculate'],
    };
    const lower = text.toLowerCase();
    let detected = 'conversation';
    for (const [k, words] of Object.entries(keywords)) {
      if (words.some(w => lower.includes(w))) { detected = k; break; }
    }
    
    document.getElementById('intentBar').style.display = 'flex';
    document.getElementById('intentBadge').textContent = detected;
    
    const steerMap = {
      question: 'Concise & factual', code: 'Precise + examples',
      analysis: 'Structured & thorough', creative: 'Expansive & imaginative',
      task: 'Action-oriented & step-by-step', conversation: 'Warm & engaging',
    };
    document.getElementById('steerText').textContent = steerMap[detected] || '–';
  }, 400);
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!state.isStreaming && state.currentAgent) sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function setInput(text) {
  if (!state.currentAgent) { toast('Select an agent first', 'info'); return; }
  const inp = document.getElementById('messageInput');
  inp.value = text;
  autoResize(inp);
  detectIntent(text);
  inp.focus();
}

async function sendMessage() {
  if (state.isStreaming || !state.currentAgent) return;
  const input = document.getElementById('messageInput');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  autoResize(input);
  state.isStreaming = true;
  document.getElementById('sendBtn').disabled = true;
  setStatus('Thinking...', 'var(--accent)');

  appendUserMessage(msg);
  const streamEl = createStreamingMessage();
  
  const start = Date.now();
  let fullResponse = '';
  let thoughts = [];
  let toolCalls = [];
  let workflowSteps = [];
  let workflowStepEls = {};

  try {
    const body = {
      agent_id: state.currentAgent.id,
      conversation_id: state.currentConvId || undefined,
      message: msg,
      use_workflow: state.workflowEnabled,
    };

    const response = await fetch(`${API}/chat/send`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      
      const lines = buffer.split('\n');
      buffer = lines.pop();
      
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') break;
        
        try {
          const event = JSON.parse(raw);
          handleStreamEvent(event, streamEl, thoughts, toolCalls, workflowSteps, workflowStepEls, (r) => { fullResponse = r; });
        } catch {}
      }
    }

    // Finalize
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    state.metrics.messages++;
    setStatus('Ready', 'var(--accent3)');
    document.getElementById('sendBtn').disabled = false;
    state.isStreaming = false;
    await loadConversations();

  } catch (e) {
    appendError('Connection error: ' + e.message);
    setStatus('Error', 'var(--danger)');
    document.getElementById('sendBtn').disabled = false;
    state.isStreaming = false;
  }
}

function handleStreamEvent(event, streamEl, thoughts, toolCalls, workflowSteps, stepEls, setResponse) {
  const type = event.type;
  const streamType = event.stream_type;

  // Workflow events
  if (streamType === 'workflow') {
    if (type === 'workflow_start') {
      renderWorkflowStart(event.total_steps);
    } else if (type === 'step_start') {
      renderWorkflowStep(event.step, event.step_index, 'running', stepEls);
    } else if (type === 'step_complete') {
      renderWorkflowStep(event.step, event.step_index, 'completed', stepEls);
    } else if (type === 'step_failed') {
      renderWorkflowStep(event.step, event.step_index, 'failed', stepEls);
    } else if (type === 'workflow_complete') {
      document.getElementById('workflowStatus')?.remove();
    }
    return;
  }

  // LLM events
  if (type === 'status') {
    setStatus(event.content, 'var(--accent)');
  } else if (type === 'thinking_start') {
    addThoughtPanel(streamEl);
    setStatus('Reasoning...', 'var(--accent2)');
  } else if (type === 'thought') {
    addThoughtStep(event.content);
    thoughts.push(event.content);
  } else if (type === 'thinking_end') {
    setStatus('Composing...', 'var(--accent)');
  } else if (type === 'tool_call') {
    addToolCall(streamEl, event.tool, event.args);
    setStatus(`Running ${event.tool}...`, 'var(--accent3)');
  } else if (type === 'tool_result') {
    updateToolResult(event.tool, event.result);
    toolCalls.push({tool: event.tool, result: event.result});
  } else if (type === 'response') {
    appendToStream(streamEl, event.content);
    setStatus('Streaming...', 'var(--accent)');
  } else if (type === 'complete') {
    setResponse(event.full_response || '');
    finalizeStream(streamEl);
  } else if (type === 'error') {
    appendError(event.content);
  } else if (type === 'meta') {
    if (event.conversation_id) state.currentConvId = event.conversation_id;
  }
}

// ===== MESSAGE RENDERING =====
function appendUserMessage(content) {
  const area = document.getElementById('messagesArea');
  document.getElementById('emptyState')?.style.setProperty('display', 'none');
  area.innerHTML += `
    <div class="message user">
      <div class="msg-content">
        <div class="msg-bubble">${formatContent(content)}</div>
        <div class="msg-meta">${new Date().toLocaleTimeString()}</div>
      </div>
    </div>
  `;
  scrollToBottom();
}

function appendAssistantMessage(content, thoughtProcess, toolCalls) {
  const area = document.getElementById('messagesArea');
  const thoughtHtml = thoughtProcess ? `
    <div class="thought-panel">
      <div class="thought-header" onclick="toggleThoughts(this)">
        Thought Process <span style="margin-left:auto">▾</span>
      </div>
      <div class="thought-steps">
        ${thoughtProcess.split('\n').filter(s => s.trim()).map(s =>
          `<div class="thought-step">${escHtml(s)}</div>`
        ).join('')}
      </div>
    </div>
  ` : '';
  
  area.innerHTML += `
    <div class="message assistant">
      <div class="msg-content">
        ${thoughtHtml}
        <div class="msg-bubble">${formatContent(content)}</div>
        <div class="msg-meta">${new Date().toLocaleTimeString()}</div>
      </div>
    </div>
  `;
  scrollToBottom();
}

function createStreamingMessage() {
  const area = document.getElementById('messagesArea');
  const id = 'stream_' + Date.now();
  const emptyState = document.getElementById('emptyState');
  if (emptyState) emptyState.style.display = 'none';
  
  const html = `
    <div class="message assistant" id="${id}">
      <div class="msg-content" id="${id}_content">
        <div class="typing-indicator">
          <div class="typing-dots">
            <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
          </div>
          <span class="stream-status" id="${id}_status">Initializing...</span>
        </div>
      </div>
    </div>
  `;
  area.insertAdjacentHTML('beforeend', html);
  scrollToBottom();
  return id;
}

function setStatus(text, color) {
  const statusEl = document.querySelector(`[id$="_status"]`);
  if (statusEl) statusEl.textContent = text;
  document.getElementById('statusDot').style.background = color;
  document.getElementById('statusText').textContent = text;
}

let currentThoughtEl = null;
function addThoughtPanel(streamId) {
  const content = document.getElementById(streamId + '_content');
  if (!content) return;
  const typing = content.querySelector('.typing-indicator');
  if (typing) typing.remove();
  
  const panel = document.createElement('div');
  panel.className = 'thought-panel';
  panel.id = streamId + '_thoughts';
  panel.innerHTML = `
    <div class="thought-header" onclick="toggleThoughts(this)">
      Reasoning <span class="thought-count" style="color:var(--text3);margin-left:4px">0 steps</span>
      <span style="margin-left:auto">▾</span>
    </div>
    <div class="thought-steps" id="${streamId}_steps"></div>
  `;
  content.appendChild(panel);
  currentThoughtEl = streamId;
  scrollToBottom();
}

let thoughtCount = 0;
function addThoughtStep(text) {
  if (!currentThoughtEl) return;
  thoughtCount++;
  const steps = document.getElementById(currentThoughtEl + '_steps');
  if (!steps) return;
  steps.innerHTML += `<div class="thought-step" style="animation:fadeIn 0.2s ease">${escHtml(text)}</div>`;
  const count = steps.closest('.thought-panel')?.querySelector('.thought-count');
  if (count) count.textContent = `${thoughtCount} steps`;
  scrollToBottom();
}

function addToolCall(streamId, tool, args) {
  const content = document.getElementById(streamId + '_content');
  if (!content) return;
  
  const block = document.createElement('div');
  block.className = 'tool-call-block';
  block.id = `tool_${tool}_${Date.now()}`;
  block.innerHTML = `
    <div class="tool-call-header"> Calling tool: <strong>${tool}</strong></div>
    <div class="tool-result" id="tool_result_${tool}">
      <span style="color:var(--text3)">Executing...</span>
    </div>
  `;
  content.appendChild(block);
  scrollToBottom();
}

function updateToolResult(tool, result) {
  const el = document.getElementById(`tool_result_${tool}`);
  if (el) el.innerHTML = escHtml(result).replace(/\n/g, '<br>');
}

function appendToStream(streamId, chunk) {
  let content = document.getElementById(streamId + '_content');
  if (!content) return;
  
  // Remove typing indicator if present
  const typing = content.querySelector('.typing-indicator');
  if (typing) typing.remove();
  
  let bubble = content.querySelector('.msg-bubble');
  if (!bubble) {
    bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    content.appendChild(bubble);
  }
  bubble.textContent += chunk;
  scrollToBottom();
}

function finalizeStream(streamId) {
  const content = document.getElementById(streamId + '_content');
  if (!content) return;
  const bubble = content.querySelector('.msg-bubble');
  if (bubble) {
    const text = bubble.textContent;
    bubble.innerHTML = formatContent(text);
  }
  const typing = content.querySelector('.typing-indicator');
  if (typing) typing.remove();
  
  // Add timestamp
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = new Date().toLocaleTimeString();
  content.appendChild(meta);
  
  thoughtCount = 0;
  currentThoughtEl = null;
  scrollToBottom();
}

function appendError(msg) {
  const area = document.getElementById('messagesArea');
  area.insertAdjacentHTML('beforeend', `
    <div style="text-align:center;padding:10px">
      <span style="background:rgba(239,68,68,0.1);border:1px solid var(--danger);color:var(--danger);padding:6px 12px;border-radius:6px;font-size:12px;font-family:Space Mono,monospace">⚠ ${escHtml(msg)}</span>
    </div>
  `);
  scrollToBottom();
}

// ===== WORKFLOW PANEL =====
function renderWorkflowStart(totalSteps) {
  const content = document.getElementById('tab-workflow');
  content.innerHTML = `
    <div style="padding:10px 0;border-bottom:1px solid var(--border);margin-bottom:8px" id="workflowStatus">
      <div style="font-size:11px;font-family:Space Mono,monospace;color:var(--accent)">▶ RUNNING — ${totalSteps} steps</div>
    </div>
    <div id="workflowSteps"></div>
  `;
}

function renderWorkflowStep(step, index, status, stepEls) {
  const container = document.getElementById('workflowSteps');
  if (!container) return;
  
  const icons = { pending: '◯', running: '◎', completed: '✓', failed: '✗' };
  const el = stepEls[step.step_id];
  
  if (el) {
    el.querySelector('.step-icon').className = `step-icon ${status}`;
    el.querySelector('.step-icon').textContent = icons[status];
    if (step.result) {
      const resultStr = typeof step.result === 'object' ? JSON.stringify(step.result).slice(0, 80) : String(step.result).slice(0, 80);
      el.querySelector('.step-result').textContent = resultStr;
    }
  } else {
    const div = document.createElement('div');
    div.className = 'workflow-step';
    div.innerHTML = `
      <div class="step-icon ${status}">${icons[status]}</div>
      <div class="step-info">
        <div class="step-name">${escHtml(step.name)}</div>
        <div class="step-result" style="color:var(--text3)">–</div>
      </div>
    `;
    container.appendChild(div);
    stepEls[step.step_id] = div;
  }
}

// ===== AGENT MODAL =====
function openModal(id) {
  document.getElementById(id).classList.add('open');
  if (id === 'agentModal') populateSkillCheckboxes();
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
  state.editingAgent = null;
}

function populateSkillCheckboxes(selectedSkills = []) {
  const cont = document.getElementById('skillsCheckboxes');
  const checks = cont.querySelectorAll('.skill-checkbox');
  checks.forEach(c => { c.checked = selectedSkills.includes(c.value); });
}

async function saveAgent() {
  const name = document.getElementById('agentName').value.trim();
  if (!name) return toast('Name required', 'error');
  
  const skills = Array.from(document.querySelectorAll('.skill-checkbox:checked')).map(c => c.value);
  
  const body = {
    name,
    description: document.getElementById('agentDesc').value,
    system_prompt: document.getElementById('agentPrompt').value || 'You are a helpful AI assistant.',
    model: document.getElementById('agentModel').value,
    temperature: parseFloat(document.getElementById('agentTemp').value),
    skills,
  };
  
  try {
    let r;
    if (state.editingAgent) {
      r = await fetch(`${API}/agents/${state.editingAgent}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    } else {
      r = await fetch(`${API}/agents`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail);
    toast(state.editingAgent ? 'Agent updated!' : 'Agent created!', 'success');
    closeModal('agentModal');
    await loadAgents();
  } catch (e) {
    toast(e.message, 'error');
  }
}

function editCurrentAgent() {
  if (!state.currentAgent) return;
  state.editingAgent = state.currentAgent.id;
  document.getElementById('agentModalTitle').textContent = '✎ Edit Agent';
  document.getElementById('agentName').value = state.currentAgent.name;
  document.getElementById('agentDesc').value = state.currentAgent.description || '';
  document.getElementById('agentPrompt').value = state.currentAgent.system_prompt || '';
  document.getElementById('agentModel').value = state.currentAgent.model || 'gemini-2.0-flash';
  document.getElementById('agentTemp').value = state.currentAgent.temperature || 0.7;
  document.getElementById('tempVal').textContent = state.currentAgent.temperature || 0.7;
  openModal('agentModal');
  populateSkillCheckboxes(state.currentAgent.skills || []);
}

// ===== SETTINGS =====
async function saveSettings() {
  const key = document.getElementById('apiKeyInput').value.trim();
  const model = document.getElementById('settingsModel').value;
  
  try {
    await fetch(`${API}/system/settings`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({gemini_api_key: key || undefined, default_model: model}),
    });
    toast('Settings saved!', 'success');
    closeModal('settingsModal');
    await checkApiKey();
  } catch {
    toast('Failed to save settings', 'error');
  }
}

// ===== MISC =====
function clearChat() {
  state.currentConvId = null;
  clearMessages();
}

function clearMessages() {
  const area = document.getElementById('messagesArea');
  area.innerHTML = `
    <div class="empty-state" id="emptyState">
      <div class="empty-icon">⬡</div>
      <div class="empty-title">Start a Conversation</div>
      <div class="empty-sub">Send a message to begin interacting with ${escHtml(state.currentAgent?.name || 'the agent')}.</div>
      <div class="suggestion-chips">
        <span class="chip" onclick="setInput('What can you help me with?')">What can you do?</span>
        <span class="chip" onclick="setInput('Calculate 15% of 2500')">Use calculator</span>
        <span class="chip" onclick="setInput('Search for latest AI trends')">Web search</span>
        <span class="chip" onclick="setInput('Explain quantum computing simply')">Explain a concept</span>
      </div>
    </div>
  `;
}

function toggleLeftSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const isHidden = sidebar.classList.toggle('sidebar-hidden');
  document.getElementById('leftToggleBtn').setAttribute('title', isHidden ? 'Show sidebar' : 'Hide sidebar');
  document.getElementById('leftToggleIcon').style.transform = isHidden ? 'rotate(180deg)' : '';
  document.getElementById('hamburgerBtn').style.display = isHidden ? 'flex' : 'none';
}

function toggleRightSidebar() {
  const panel = document.querySelector('.right-panel');
  const isHidden = panel.classList.toggle('right-panel-hidden');
  document.getElementById('rightToggleBtn').setAttribute('title', isHidden ? 'Show panel' : 'Hide panel');
  document.getElementById('rightToggleIcon').style.transform = isHidden ? 'rotate(180deg)' : '';
  document.getElementById('showRightPanelBtn').style.display = isHidden ? 'flex' : 'none';
}

function toggleWorkflow() {
  state.workflowEnabled = !state.workflowEnabled;
  document.getElementById('workflowToggle').classList.toggle('on', state.workflowEnabled);
  toast(`Workflow ${state.workflowEnabled ? 'enabled' : 'disabled'}`, 'info');
}

function switchPanel(name, btn) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-agents').style.display = 'none';
  document.getElementById('panel-convs').style.display = 'none';
  document.getElementById('panel-skills').style.display = 'none';
  document.getElementById(`panel-${name}`).style.display = 'block';
  if (name === 'convs') loadConversations();
}

function switchRightTab(name, btn) {
  document.querySelectorAll('.right-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  
  const content = document.getElementById('rightContent');
  if (name === 'workflow') {
    if (!document.getElementById('tab-workflow')) {
      content.innerHTML = `<div id="tab-workflow"><div style="color:var(--text3);font-size:12px;text-align:center;padding:30px 12px"><div style="font-size:32px;opacity:0.3;margin-bottom:8px">◈</div>Workflow steps appear here</div></div>`;
    }
  } else if (name === 'metrics') {
    content.innerHTML = `
      <div id="tab-metrics">
        <div class="metric-card">
          <div class="metric-label">MESSAGES SENT</div>
          <div class="metric-value">${state.metrics.messages}</div>
          <div class="metric-sub">this session</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">ACTIVE CONNECTIONS</div>
          <div class="metric-value" id="wsConnCount">1</div>
          <div class="metric-sub">WebSocket clients</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">INTENT ANALYSIS</div>
          <div class="intent-meter">
            ${['question','task','creative','analysis','code','conversation'].map(i => `
              <div class="intent-row">
                <span class="intent-label">${i}</span>
                <div class="intent-bar-wrap"><div class="intent-bar-fill" style="width:${Math.random()*70+10}%"></div></div>
                <span class="intent-score">${(Math.random()*0.7+0.1).toFixed(2)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  } else if (name === 'context') {
    content.innerHTML = `
      <div id="tab-context">
        <div class="metric-card">
          <div class="metric-label">CURRENT AGENT</div>
          <div style="font-size:14px;font-weight:700;color:var(--text);margin-top:4px">${escHtml(state.currentAgent?.name || 'None selected')}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">MODEL</div>
          <div style="font-size:13px;font-family:Space Mono,monospace;color:var(--accent);margin-top:4px">${state.currentAgent?.model || '–'}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">SYSTEM PROMPT</div>
          <div style="font-size:11px;color:var(--text3);margin-top:4px;line-height:1.5">${escHtml((state.currentAgent?.system_prompt || '').slice(0, 150))}${(state.currentAgent?.system_prompt || '').length > 150 ? '...' : ''}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">ACTIVE SKILLS</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:6px">
            ${(state.currentAgent?.skills || []).map(s => `<span class="skill-badge">${s}</span>`).join('') || '<span style="color:var(--text3);font-size:12px">None</span>'}
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">CONVERSATION ID</div>
          <div style="font-family:Space Mono,monospace;font-size:12px;color:var(--text2);margin-top:4px">${state.currentConvId || '– (new)'}</div>
        </div>
      </div>
    `;
  }
}

function toggleThoughts(header) {
  const steps = header.nextElementSibling;
  const arrow = header.querySelector('span:last-child');
  if (steps) {
    const hidden = steps.style.display === 'none';
    steps.style.display = hidden ? 'block' : 'none';
    if (arrow) arrow.textContent = hidden ? '▾' : '▸';
  }
}

function scrollToBottom() {
  const area = document.getElementById('messagesArea');
  area.scrollTop = area.scrollHeight;
}

function formatContent(text) {
  if (!text) return '';
  // Basic markdown-like formatting
  text = escHtml(text);
  // Code blocks
  text = text.replace(/```([^`]+)```/gs, '<pre><code>$1</code></pre>');
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Line breaks
  text = text.replace(/\n/g, '<br>');
  return text;
}

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function toast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// Click outside modal to close
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.classList.remove('open');
  });
});

init();