/* ─────────────────────────────────────────────────────────────
   Auditgo — app.js
   4 views: New Audit | Reports | History | Settings
   Chat: SSE streaming quick answers + deep analysis on demand
───────────────────────────────────────────────────────────── */

const STORAGE_KEYS = {
  GROQ_KEY:        'auditgo_groq_key',
  HISTORY:         'auditgo_history',
  CRAWL_MAX_PAGES: 'auditgo_max_pages',
  CRAWL_MAX_DEPTH: 'auditgo_max_depth',
};

/* ── State ───────────────────────────────────────────────── */
let currentResults         = null;
let auditHistory           = [];
let abortController        = null;
let chatConversationHistory = [];
let chatCurrentUrl          = '';
let chatIsBusy              = false;

try { auditHistory = JSON.parse(localStorage.getItem(STORAGE_KEYS.HISTORY) || '[]'); } catch(_) {}

/* ── DOM refs ─────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

const navItems        = document.querySelectorAll('.nav-item[data-view]');
const views           = document.querySelectorAll('.view');
const topbarTitle     = $('topbarTitle');
const sidebar         = $('sidebar');
const sidebarToggle   = $('sidebarToggle');
const runAuditTopBtn  = $('runAuditTopBtn');

const urlInput        = $('urlInput');
const queryInput      = $('queryInput');
const runAuditBtn     = $('runAuditBtn');
const presetCards     = document.querySelectorAll('.preset-card');

const reportsEmpty    = $('reportsEmpty');
const reportsContent  = $('reportsContent');
const goToAuditBtn    = $('goToAuditBtn');
const reportsBadge    = $('reportsBadge');
const seoCount        = $('seoCount');
const seoTableBody    = $('seoTableBody');
const napTableBody    = $('napTableBody');
const rawJson         = $('rawJson');
const reportTabs      = document.querySelectorAll('.report-tab');
const tabPanels       = document.querySelectorAll('.tab-panel');
const dlAudit         = $('dlAudit');
const dlNap           = $('dlNap');
const dlAnswer        = $('dlAnswer');

const historyEmpty    = $('historyEmpty');
const historyList     = $('historyList');
const clearHistoryBtn = $('clearHistoryBtn');

const groqKeyInput      = $('groqKeyInput');
const toggleKeyVis      = $('toggleKeyVis');
const saveGroqKey       = $('saveGroqKey');
const clearGroqKey      = $('clearGroqKey');
const maxPagesInput     = $('maxPagesInput');
const maxDepthInput     = $('maxDepthInput');
const saveCrawlSettings = $('saveCrawlSettings');

const overlay       = $('overlay');
const overlayUrl    = $('overlayUrl');
const overlayError  = $('overlayError');
const overlayCancel = $('overlayCancel');
const toast         = $('toast');

const chatMessages  = $('chatMessages');
const chatEmpty     = $('chatEmpty');
const chatInput     = $('chatInput');
const chatSendBtn   = $('chatSendBtn');
const chatSiteLabel = $('chatSiteLabel');
const chatClearBtn  = $('chatClearBtn');
const chatKeyBanner = $('chatKeyBanner');

/* ═══════════════════════════════════════════════════════════
   NAVIGATION
══════════════════════════════════════════════════════════ */
const VIEW_TITLES = { audit:'New Audit', reports:'Reports', history:'History', settings:'Settings' };

function switchView(viewId) {
  navItems.forEach(n => n.classList.toggle('active', n.dataset.view === viewId));
  views.forEach(v   => v.classList.toggle('active', v.id === `view-${viewId}`));
  if (topbarTitle) topbarTitle.textContent = VIEW_TITLES[viewId] || viewId;
  if (viewId === 'reports')  renderReports();
  if (viewId === 'history')  renderHistory();
  if (viewId === 'settings') loadSettingsUI();
}

navItems.forEach(n => n.addEventListener('click', e => { e.preventDefault(); switchView(n.dataset.view); }));
goToAuditBtn?.addEventListener('click', () => switchView('audit'));
runAuditTopBtn?.addEventListener('click', () => { switchView('audit'); setTimeout(() => urlInput?.focus(), 80); });
sidebarToggle?.addEventListener('click', () => sidebar?.classList.toggle('collapsed'));

/* ═══════════════════════════════════════════════════════════
   AUDIT EXECUTION
══════════════════════════════════════════════════════════ */
function normalizeUrl(raw) {
  raw = (raw || '').trim();
  if (!raw) return '';
  if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
  return raw;
}

async function runAudit(url, query) {
  url = normalizeUrl(url);
  if (!url) { showToast('Please enter a valid URL', 'error'); urlInput?.focus(); return; }

  const groqKey = localStorage.getItem(STORAGE_KEYS.GROQ_KEY) || '';

  overlayUrl.textContent = url;
  overlayError.style.display = 'none';
  overlay.classList.add('visible');
  setStep(1,'running'); setStep(2,'idle'); setStep(3,'idle'); setStep(4,'idle');

  const t2 = setTimeout(() => setStep(2,'running'), 800);
  const t3 = setTimeout(() => setStep(3,'running'), 2000);
  const t4 = setTimeout(() => setStep(4,'running'), 3500);
  abortController = new AbortController();

  try {
    const res = await fetch('/api/audit', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      signal:  abortController.signal,
      body:    JSON.stringify({ url, query: query?.trim() || null, groq_api_key: groqKey || null }),
    });

    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4);
    if (!res.ok) {
      let detail = `Server error ${res.status}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch(_) {}
      throw new Error(detail);
    }

    const json = await res.json();
    const data = json.data;
    if (!data) throw new Error('Empty response from server');

    currentResults      = data;
    currentResults._url = url;
    chatCurrentUrl      = url;

    // Save history
    const entry = {
      id: Date.now(), url,
      query:     query?.trim() || null,
      timestamp: new Date().toISOString(),
      findings:  (data.audit || []).length,
      hasAnswer: !!(data.answer?.excerpt),
      data,
    };
    auditHistory.unshift(entry);
    if (auditHistory.length > 50) auditHistory.pop();
    try { localStorage.setItem(STORAGE_KEYS.HISTORY, JSON.stringify(auditHistory)); } catch(_) {}

    const count = (data.audit || []).length;
    if (reportsBadge) {
      reportsBadge.style.display = count > 0 ? 'flex' : 'none';
      reportsBadge.textContent   = count;
    }

    [1,2,3,4].forEach(i => setStep(i,'done'));
    setTimeout(() => {
      overlay.classList.remove('visible');
      showToast(`Audit complete — ${count} finding${count!==1?'s':''}`, 'success');
      switchView('reports');
    }, 500);

  } catch(err) {
    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4);
    if (err.name === 'AbortError') { overlay.classList.remove('visible'); showToast('Audit cancelled'); return; }
    overlayError.textContent = err.message || 'Unknown error';
    overlayError.style.display = 'block';
    showToast('Audit failed — see overlay', 'error');
  }
}

function setStep(n, state) {
  const el  = $(`ostep${n}`);
  const dot = el?.querySelector('.step-dot');
  if (!dot) return;
  dot.classList.remove('running','done');
  el.classList.remove('done');
  if (state === 'running') dot.classList.add('running');
  if (state === 'done')    { dot.classList.add('done'); el.classList.add('done'); }
}

overlayCancel?.addEventListener('click', () => { abortController?.abort(); overlay.classList.remove('visible'); showToast('Audit cancelled'); });
runAuditBtn?.addEventListener('click', () => runAudit(urlInput?.value, queryInput?.value));
urlInput?.addEventListener('keydown',  e => { if (e.key==='Enter') runAudit(urlInput.value, queryInput?.value); });
queryInput?.addEventListener('keydown',e => { if (e.key==='Enter') runAudit(urlInput?.value, queryInput.value); });
presetCards.forEach(card => card.addEventListener('click', () => {
  const u = card.dataset.url||'', q = card.dataset.query||'';
  if (urlInput)   urlInput.value   = u;
  if (queryInput) queryInput.value = q;
  runAudit(u, q);
}));

/* ═══════════════════════════════════════════════════════════
   REPORTS
══════════════════════════════════════════════════════════ */
function renderReports(data) {
  const d = data || currentResults;
  if (!d) {
    if (reportsEmpty)   reportsEmpty.style.display   = 'flex';
    if (reportsContent) reportsContent.style.display = 'none';
    return;
  }
  if (reportsEmpty)   reportsEmpty.style.display   = 'none';
  if (reportsContent) reportsContent.style.display = 'block';

  /* SEO table */
  const audit = Array.isArray(d.audit) ? d.audit : [];
  if (seoCount) seoCount.textContent = audit.length;
  if (seoTableBody) {
    seoTableBody.innerHTML = '';
    if (!audit.length) {
      seoTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text-4)">No SEO issues detected.</td></tr>';
    } else {
      audit.forEach(item => {
        const pages = Array.isArray(item.affected_pages)
          ? item.affected_pages.map(esc).join('<br>') : esc(item.page||'—');
        const sev = (item.severity||'low').toLowerCase();
        const tr  = document.createElement('tr');
        tr.innerHTML = `
          <td style="font-weight:600;white-space:nowrap">${esc(item.metric)}</td>
          <td><span class="badge badge-${sev}">${sev}</span></td>
          <td style="word-break:break-all;font-size:11.5px">${pages}</td>
          <td><code>${esc(item.evidence)}</code></td>
          <td>${esc(item.suggested_fix)}</td>`;
        seoTableBody.appendChild(tr);
      });
    }
  }

  /* NAP table */
  const nap = Array.isArray(d.nap_report) ? d.nap_report : [];
  if (napTableBody) {
    napTableBody.innerHTML = '';
    if (!nap.length) {
      napTableBody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text-4)">No NAP data extracted.</td></tr>';
    } else {
      nap.forEach(item => {
        const verdict = (item.verdict||'unknown').toLowerCase();
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="font-weight:600">${esc(item.field)}</td>
          <td><span class="badge badge-${verdict}">${verdict.replace(/_/g,' ')}</span></td>
          <td>${esc(item.confidence)}</td>
          <td style="font-size:12px">${(item.values||[]).map(esc).join('<br>')}</td>
          <td style="font-size:12px;font-family:monospace">${(item.normalized_values||[]).map(esc).join('<br>')}</td>`;
        napTableBody.appendChild(tr);
      });
    }
  }

  /* Seed chat with initial answer */
  const ans  = d.answer || {};
  const aUrl = d._url || (auditHistory[0]?.url) || '';
  seedChat(ans, aUrl);

  /* Raw JSON */
  if (rawJson) rawJson.textContent = JSON.stringify(d, null, 2);
}

/* Report tabs */
reportTabs.forEach(btn => btn.addEventListener('click', () => {
  reportTabs.forEach(b => b.classList.remove('active'));
  tabPanels.forEach(p  => p.classList.remove('active'));
  btn.classList.add('active');
  $(btn.dataset.tab)?.classList.add('active');
}));

/* Downloads */
function download(filename, obj) {
  if (!obj) { showToast('No data to download','error'); return; }
  const a   = document.createElement('a');
  a.href     = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(obj,null,2));
  a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  showToast(`Downloaded ${filename}`);
}
dlAudit?.addEventListener('click',  () => download('audit.json',      currentResults?.audit));
dlNap?.addEventListener('click',    () => download('nap_report.json', currentResults?.nap_report));
dlAnswer?.addEventListener('click', () => download('answer.json',     currentResults?.answer));

/* ═══════════════════════════════════════════════════════════
   HISTORY
══════════════════════════════════════════════════════════ */
function renderHistory() {
  if (!historyList||!historyEmpty) return;
  historyList.innerHTML = '';
  if (!auditHistory.length) { historyEmpty.style.display='flex'; return; }
  historyEmpty.style.display = 'none';
  auditHistory.forEach(entry => {
    const div  = document.createElement('div');
    div.className = 'history-item';
    const date = new Date(entry.timestamp).toLocaleString();
    div.innerHTML = `
      <div class="history-item-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
      </div>
      <div class="history-item-body">
        <div class="history-item-url">${esc(entry.url)}</div>
        <div class="history-item-meta">
          <span>${date}</span>
          <span>${entry.findings} finding${entry.findings!==1?'s':''}</span>
          ${entry.hasAnswer ? '<span style="color:var(--blue)">Q&A answered</span>' : ''}
        </div>
      </div>
      <div class="history-item-actions">
        <button class="history-action-btn" data-id="${entry.id}" data-action="view">View</button>
        <button class="history-action-btn" data-id="${entry.id}" data-action="rerun">Re-run</button>
      </div>`;
    historyList.appendChild(div);
  });
  historyList.querySelectorAll('.history-action-btn').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const entry = auditHistory.find(h => h.id == btn.dataset.id);
    if (!entry) return;
    if (btn.dataset.action === 'view') { currentResults = entry.data; switchView('reports'); }
    else { if (urlInput) urlInput.value = entry.url; if (queryInput) queryInput.value = entry.query||''; switchView('audit'); setTimeout(() => runAudit(entry.url, entry.query||''), 120); }
  }));
}
clearHistoryBtn?.addEventListener('click', () => {
  if (!confirm('Clear all audit history?')) return;
  auditHistory = [];
  try { localStorage.removeItem(STORAGE_KEYS.HISTORY); } catch(_) {}
  renderHistory();
  showToast('History cleared');
});

/* ═══════════════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════════════ */
function loadSettingsUI() {
  if (groqKeyInput)  groqKeyInput.value   = localStorage.getItem(STORAGE_KEYS.GROQ_KEY)||'';
  if (maxPagesInput) maxPagesInput.value  = localStorage.getItem(STORAGE_KEYS.CRAWL_MAX_PAGES)||150;
  if (maxDepthInput) maxDepthInput.value  = localStorage.getItem(STORAGE_KEYS.CRAWL_MAX_DEPTH)||4;
}
saveGroqKey?.addEventListener('click', () => {
  const val = groqKeyInput?.value.trim();
  if (val) { localStorage.setItem(STORAGE_KEYS.GROQ_KEY, val); showToast('API key saved','success'); }
  else     { localStorage.removeItem(STORAGE_KEYS.GROQ_KEY);   showToast('API key removed'); }
  updateChatKeyBanner();
});
clearGroqKey?.addEventListener('click', () => {
  localStorage.removeItem(STORAGE_KEYS.GROQ_KEY);
  if (groqKeyInput) groqKeyInput.value = '';
  updateChatKeyBanner();
  showToast('API key removed');
});
toggleKeyVis?.addEventListener('click', () => {
  if (!groqKeyInput) return;
  const show = groqKeyInput.type === 'password';
  groqKeyInput.type = show ? 'text' : 'password';
  $('eyeIcon').innerHTML = show
    ? '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>'
    : '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
});
saveCrawlSettings?.addEventListener('click', () => {
  const p = Math.min(Math.max(parseInt(maxPagesInput?.value)||150,5),500);
  const d = Math.min(Math.max(parseInt(maxDepthInput?.value)||4,1),10);
  localStorage.setItem(STORAGE_KEYS.CRAWL_MAX_PAGES, p);
  localStorage.setItem(STORAGE_KEYS.CRAWL_MAX_DEPTH, d);
  showToast('Crawl settings saved','success');
});

/* ═══════════════════════════════════════════════════════════
   CHAT MODULE  — SSE streaming, quick + deep tiers
══════════════════════════════════════════════════════════ */

function updateChatKeyBanner() {
  const key = localStorage.getItem(STORAGE_KEYS.GROQ_KEY)||'';
  if (chatKeyBanner) chatKeyBanner.style.display = key ? 'none' : 'flex';
}

function seedChat(ans, url) {
  if (!chatMessages) return;
  chatCurrentUrl = url || '';
  chatConversationHistory = [];

  if (chatSiteLabel) {
    try { chatSiteLabel.textContent = chatCurrentUrl ? `Site: ${new URL(chatCurrentUrl).hostname}` : ''; }
    catch(_) { chatSiteLabel.textContent = ''; }
  }

  chatMessages.innerHTML = '';
  const emptyEl = createEmptyState('Run an audit with a question to start the conversation.');
  chatMessages.appendChild(emptyEl);

  updateChatKeyBanner();

  if (!ans || (!ans.query && !ans.answer && !ans.excerpt)) return;
  emptyEl.style.display = 'none';

  if (Array.isArray(ans.conversation_history)) chatConversationHistory = [...ans.conversation_history];
  if (ans.query) appendUserBubble(ans.query);

  const display = ans.answer || ans.excerpt;
  if (display) {
    appendAssistantBubble(
      display,
      ans.sources || (ans.url&&ans.excerpt ? [{url:ans.url,excerpt:ans.excerpt}] : []),
      ans.confidence || 0,
      ans.synthesized || false,
    );
  } else {
    appendAssistantBubble('No relevant information was found. Try rephrasing or asking something else.', [], 0, false);
  }
}

/* ── Send (quick streaming by default) ─────────────────── */
async function sendChat(deep = false) {
  if (!chatInput || chatIsBusy) return;
  const question = chatInput.value.trim();
  if (!question) return;

  if (!chatCurrentUrl) { showToast('Run an audit first to enable Q&A','error'); return; }

  chatInput.value = '';
  chatIsBusy = true;
  if (chatSendBtn) chatSendBtn.disabled = true;

  const emptyEl = document.getElementById('chatEmpty');
  if (emptyEl) emptyEl.style.display = 'none';

  appendUserBubble(question);

  const { bubble, textNode, metaRow } = appendStreamingBubble(deep);
  const groqKey = localStorage.getItem(STORAGE_KEYS.GROQ_KEY) || '';

  let fullText  = '';
  let finalData = null;

  try {
    const res = await fetch('/api/chat/stream', {
      method:  'POST',
      headers: {'Content-Type':'application/json'},
      body:    JSON.stringify({
        url:                  chatCurrentUrl,
        question,
        conversation_history: chatConversationHistory,
        groq_api_key:         groqKey || null,
        deep,
      }),
    });

    if (!res.ok) {
      let detail = `Server error ${res.status}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch(_) {}
      throw new Error(detail);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();                   // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const ev = JSON.parse(line.slice(6));
          if (ev.token) {
            fullText += ev.token;
            textNode.textContent = fullText;
            scrollChatBottom();
          }
          if (ev.done) {
            finalData = ev;
          }
        } catch(_) {}
      }
    }
  } catch(err) {
    fullText = `Sorry, I couldn't process that. ${err.message}`;
    textNode.textContent = fullText;
  }

  // Remove streaming cursor
  bubble.classList.remove('streaming');

  // Finalize bubble with sources + confidence + deep button
  if (finalData) {
    finalizeStreamingBubble(bubble, metaRow, finalData, question, deep);
    // Update conversation history
    chatConversationHistory = chatConversationHistory.slice(-10);
    chatConversationHistory.push({ role: 'user',      content: question });
    chatConversationHistory.push({ role: 'assistant', content: fullText });
  }

  chatIsBusy = false;
  if (chatSendBtn) chatSendBtn.disabled = false;
  chatInput?.focus();
}

/* ── Bubble builders ────────────────────────────────────── */
function appendUserBubble(text) {
  if (!chatMessages) return;
  const div = document.createElement('div');
  div.className = 'chat-turn';
  div.innerHTML = `<div class="chat-msg-user">${esc(text)}</div>`;
  chatMessages.appendChild(div);
  scrollChatBottom();
}

function appendStreamingBubble(deep) {
  const turn = document.createElement('div');
  turn.className = 'chat-turn';

  const assistant = document.createElement('div');
  assistant.className = 'chat-msg-assistant';

  /* Mode label */
  const modeLabel = document.createElement('div');
  modeLabel.className = 'chat-mode-label';
  modeLabel.textContent = deep ? 'Deep Analysis' : 'Quick Answer';

  /* Bubble with streaming cursor */
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble streaming';
  const textNode = document.createTextNode('');
  bubble.appendChild(textNode);

  /* Placeholder for sources + actions (filled on done) */
  const metaRow = document.createElement('div');
  metaRow.className = 'chat-meta-row';

  assistant.append(modeLabel, bubble, metaRow);
  turn.appendChild(assistant);
  chatMessages.appendChild(turn);
  scrollChatBottom();
  return { bubble, textNode, metaRow };
}

function finalizeStreamingBubble(bubble, metaRow, ev, question, wasDeep) {
  const sources    = ev.sources    || [];
  const confidence = ev.confidence || 0;
  const hasKey     = ev.has_key    || false;

  /* Confidence pill */
  const confClass = confidence >= 0.6 ? 'confidence-high'
                  : confidence >= 0.3 ? 'confidence-medium'
                  : 'confidence-low';
  const confLabel = confidence >= 0.6 ? 'High confidence'
                  : confidence >= 0.3 ? 'Medium confidence'
                  : 'Low confidence';

  if (confidence > 0) {
    const pill = document.createElement('div');
    pill.className = `confidence-pill ${confClass}`;
    pill.textContent = confLabel;
    bubble.appendChild(pill);
  }

  /* Sources */
  if (sources.length) {
    const srcSection = document.createElement('div');
    srcSection.className = 'chat-sources';
    srcSection.innerHTML = `<div class="chat-source-label">Sources from this website</div>` +
      sources.slice(0,3).map((s,i) => `
        <div class="chat-source-item">
          <div class="chat-source-num">${i+1}</div>
          <div class="chat-source-body">
            <a href="${esc(s.url)}" target="_blank" rel="noopener" class="chat-source-url">${esc(s.url)}</a>
            <div class="chat-source-excerpt">${esc(s.excerpt)}</div>
          </div>
        </div>`).join('');
    metaRow.appendChild(srcSection);
  }

  /* Deep analysis button — only show after quick answers */
  if (!wasDeep && hasKey) {
    const deepBtn = document.createElement('button');
    deepBtn.className   = 'btn-deep-analysis';
    deepBtn.innerHTML   = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      Deep Analysis`;
    deepBtn.addEventListener('click', () => {
      deepBtn.disabled = true;
      deepBtn.textContent = 'Analyzing…';
      if (chatInput) chatInput.value = question;
      sendChat(true);   // re-ask same question in deep mode
    });
    metaRow.appendChild(deepBtn);
  } else if (!wasDeep && !hasKey) {
    /* No-key nudge */
    const nudge = document.createElement('div');
    nudge.className = 'chat-key-nudge';
    nudge.innerHTML = `Add a <button class="nudge-link" onclick="switchView('settings')">Groq API key</button> for AI-synthesized answers and Deep Analysis.`;
    metaRow.appendChild(nudge);
  }

  scrollChatBottom();
}

function appendAssistantBubble(text, sources, confidence, synthesized) {
  const turn      = document.createElement('div');
  turn.className  = 'chat-turn';
  const assistant = document.createElement('div');
  assistant.className = 'chat-msg-assistant';

  const modeLabel = document.createElement('div');
  modeLabel.className = 'chat-mode-label';
  modeLabel.textContent = synthesized ? 'AI Answer' : 'Extracted Answer';

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;

  if (confidence > 0) {
    const confClass = confidence >= 0.6 ? 'confidence-high' : confidence >= 0.3 ? 'confidence-medium' : 'confidence-low';
    const confLabel = confidence >= 0.6 ? 'High confidence' : confidence >= 0.3 ? 'Medium confidence' : 'Low confidence';
    const pill = document.createElement('div');
    pill.className = `confidence-pill ${confClass}`;
    pill.textContent = confLabel;
    bubble.appendChild(pill);
  }

  let sourcesHtml = '';
  if (sources && sources.length) {
    sourcesHtml = `<div class="chat-sources">
      <div class="chat-source-label">Sources from this website</div>
      ${sources.slice(0,3).map((s,i) => `
        <div class="chat-source-item">
          <div class="chat-source-num">${i+1}</div>
          <div class="chat-source-body">
            <a href="${esc(s.url)}" target="_blank" rel="noopener" class="chat-source-url">${esc(s.url)}</a>
            <div class="chat-source-excerpt">${esc(s.excerpt)}</div>
          </div>
        </div>`).join('')}
    </div>`;
  }

  assistant.innerHTML = '';
  assistant.append(modeLabel, bubble);
  if (sourcesHtml) assistant.insertAdjacentHTML('beforeend', sourcesHtml);
  turn.appendChild(assistant);
  chatMessages.appendChild(turn);
  scrollChatBottom();
}

function createEmptyState(msg) {
  const d = document.createElement('div');
  d.className = 'chat-empty';
  d.id = 'chatEmpty';
  d.innerHTML = `
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="1.5" stroke-linecap="round">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg>
    <p>${esc(msg)}</p>`;
  return d;
}

function scrollChatBottom() {
  if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
}

/* Chat event listeners */
chatSendBtn?.addEventListener('click', () => sendChat(false));
chatInput?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(false); });
chatClearBtn?.addEventListener('click', () => {
  chatConversationHistory = [];
  if (chatMessages) {
    chatMessages.innerHTML = '';
    chatMessages.appendChild(createEmptyState('Conversation cleared. Ask a new question below.'));
  }
});

/* ═══════════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════════ */
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

let toastTimer;
function showToast(msg, type = '') {
  if (!toast) return;
  toast.textContent = msg;
  toast.className   = `toast ${type} visible`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200);
}

/* ── Init ────────────────────────────────────────────────── */
(function init() {
  if (auditHistory.length > 0 && auditHistory[0].data) {
    currentResults = auditHistory[0].data;
    const count    = (auditHistory[0].data.audit||[]).length;
    if (reportsBadge && count > 0) { reportsBadge.style.display='flex'; reportsBadge.textContent=count; }
    chatCurrentUrl = auditHistory[0].url || '';
    if (chatSiteLabel && chatCurrentUrl) {
      try { chatSiteLabel.textContent = `Site: ${new URL(chatCurrentUrl).hostname}`; } catch(_) {}
    }
  }
  updateChatKeyBanner();
})();
