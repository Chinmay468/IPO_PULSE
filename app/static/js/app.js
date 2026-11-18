// ==================== MAIN APPLICATION CONTROLLER ====================

// Tab Switching
function switchTab(tabId) {
  currentActiveTab = tabId;
  document.querySelectorAll('main > section').forEach(sec => sec.classList.add('hidden'));
  const activeSection = document.getElementById('tab-' + tabId);
  if (activeSection) activeSection.classList.remove('hidden');

  // Update Desktop and Mobile Tabs
  ['ipos', 'allotment', 'applications', 'methodology'].forEach(t => {
    const btn = document.getElementById('nav-' + t);
    const mBtn = document.getElementById('mobile-nav-' + t);
    if (t === tabId) {
      if (btn) btn.className = "h-full px-3 text-xs font-bold text-emerald-600 dark:text-emerald-400 border-b-2 border-emerald-500 transition-all flex items-center gap-1.5 cursor-pointer";
      if (mBtn) mBtn.className = "flex-1 py-1.5 px-2.5 text-center text-xs font-bold rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 shrink-0 cursor-pointer";
    } else {
      if (btn) btn.className = "h-full px-3 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white border-b-2 border-transparent transition-all flex items-center gap-1.5 cursor-pointer";
      if (mBtn) mBtn.className = "flex-1 py-1.5 px-2.5 text-center text-xs font-semibold rounded-lg text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 shrink-0 cursor-pointer";
    }
  });

  if (tabId === 'allotment') loadRegistrarCompanies();
  if (tabId === 'applications') loadMyApplications();
  if (tabId === 'methodology') loadScoringMethodology();
  if (tabId === 'ipos') loadIpos();
  refreshLucideIcons();
}

// 15s Live Sync Controller
function initLiveSync() {
  if (liveSyncInterval) clearInterval(liveSyncInterval);
  liveSyncInterval = setInterval(() => {
    if (!liveSyncEnabled) return;
    if (currentActiveTab === 'ipos') {
      loadIpos(true);
    }
  }, 15000);
}

function toggleLiveSync() {
  liveSyncEnabled = !liveSyncEnabled;
  const ping = document.getElementById('live-ping');
  const dot = document.getElementById('live-dot');
  const text = document.getElementById('live-sync-text');

  if (liveSyncEnabled) {
    if (ping) ping.classList.remove('hidden');
    if (dot) dot.className = 'relative inline-flex rounded-full h-2 w-2 bg-emerald-500';
    if (text) text.textContent = 'Live: 15s';
    if (currentActiveTab === 'ipos') loadIpos(true);
  } else {
    if (ping) ping.classList.add('hidden');
    if (dot) dot.className = 'relative inline-flex rounded-full h-2 w-2 bg-slate-400';
    if (text) text.textContent = 'Live: OFF';
  }
}

async function syncMarketData() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const btn = document.getElementById('sync-btn');
  const icon = document.getElementById('sync-icon');
  if (icon) icon.classList.add('animate-spin');
  try {
    const res = await fetch('/api/v1/scraper/sync', { method: 'POST', headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      openLoginModal();
      return;
    }
    await loadIpos();
  } catch (err) {
    console.error("Sync error:", err);
  } finally {
    if (icon) icon.classList.remove('animate-spin');
  }
}

// ==================== IPO AI COPILOT CONTROLLER ====================
let aiVoiceEnabled = false;

function openAICopilot() {
  openAICopilotModal();
}

function openAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (!modal) return;
  modal.classList.remove('ai-modal-closed');
  modal.classList.add('ai-modal-open');
  const chatMessages = document.getElementById('ai-modal-chat-messages');
  if (chatMessages && chatMessages.children.length === 0) {
    renderAICopilotWelcome();
  }
  const input = document.getElementById('ai-modal-input');
  if (input) setTimeout(() => input.focus(), 150);
  refreshLucideIcons();
}

function closeAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (!modal) return;
  modal.classList.remove('ai-modal-open');
  modal.classList.add('ai-modal-closed');
}

function toggleAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (!modal) return;
  if (modal.classList.contains('ai-modal-open')) {
    closeAICopilotModal();
  } else {
    openAICopilotModal();
  }
}

function resetAICopilotChat() {
  aiChatHistory = [];
  const chatMessages = document.getElementById('ai-modal-chat-messages');
  if (chatMessages) {
    chatMessages.innerHTML = '';
    renderAICopilotWelcome();
  }
}

function toggleAICopilotVoice() {
  aiVoiceEnabled = !aiVoiceEnabled;
  const icon = document.getElementById('ai-voice-icon');
  if (icon) {
    icon.className = aiVoiceEnabled ? 'w-4 h-4 text-emerald-500' : 'w-4 h-4 text-slate-400';
  }
  if (!aiVoiceEnabled && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
}

function renderAICopilotWelcome() {
  const chat = document.getElementById('ai-modal-chat-messages');
  if (!chat) return;

  chat.innerHTML = `
    <div id="ai-welcome-box" class="p-3.5 rounded-2xl bg-gradient-to-br from-amber-50 to-orange-50/50 dark:from-slate-900/90 dark:to-slate-900/60 border border-amber-200/60 dark:border-slate-800 space-y-2">
      <div class="flex items-center gap-2 text-amber-900 dark:text-amber-300 font-bold text-xs">
        <i data-lucide="sparkles" class="w-4 h-4 text-amber-500"></i>
        <span>IPO Pulse AI Copilot</span>
      </div>
      <p class="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
        Ask me anything about current and upcoming IPOs, Grey Market Premium (GMP), subscription trends, allotment chances, or scoring breakdown.
      </p>
      <div class="pt-1.5 flex flex-wrap gap-1.5">
        <button type="button" onclick="askQuickPrompt('Which Mainboard IPO should I apply for right now?')" class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200/80 dark:border-slate-700 hover:border-amber-400 transition cursor-pointer">
          ⭐ Best IPO to Apply?
        </button>
        <button type="button" onclick="askQuickPrompt('What are the latest GMP trends for active IPOs?')" class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200/80 dark:border-slate-700 hover:border-amber-400 transition cursor-pointer">
          📈 Latest GMP Trends
        </button>
        <button type="button" onclick="askQuickPrompt('Explain how the 0-100 IPO composite score is calculated')" class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200/80 dark:border-slate-700 hover:border-amber-400 transition cursor-pointer">
          🧮 Scoring Formula
        </button>
      </div>
    </div>
  `;
  refreshLucideIcons();
}

function askQuickPrompt(promptText) {
  const input = document.getElementById('ai-modal-input');
  if (input) {
    input.value = promptText;
    submitAICopilotChat(new Event('submit'));
  }
}

function toggleQuickPromptSuggestions() {
  const chat = document.getElementById('ai-modal-chat-messages');
  if (!chat) return;
  const existing = document.getElementById('ai-quick-suggestions-box');
  if (existing) {
    existing.remove();
    return;
  }
  const box = document.createElement('div');
  box.id = 'ai-quick-suggestions-box';
  box.className = 'p-3 rounded-xl bg-slate-100/80 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 space-y-1.5 my-2';
  box.innerHTML = `
    <div class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Suggested Questions</div>
    <div class="space-y-1">
      <button type="button" onclick="askQuickPrompt('Which upcoming IPOs have high GMP?')" class="w-full text-left text-[11px] text-slate-700 dark:text-slate-200 hover:text-amber-600 dark:hover:text-amber-400 py-0.5">
        • Which upcoming IPOs have high GMP?
      </button>
      <button type="button" onclick="askQuickPrompt('What is the difference between Mainboard and SME IPOs?')" class="w-full text-left text-[11px] text-slate-700 dark:text-slate-200 hover:text-amber-600 dark:hover:text-amber-400 py-0.5">
        • What is the difference between Mainboard and SME IPOs?
      </button>
      <button type="button" onclick="askQuickPrompt('How can I check allotment status for Link Intime issues?')" class="w-full text-left text-[11px] text-slate-700 dark:text-slate-200 hover:text-amber-600 dark:hover:text-amber-400 py-0.5">
        • How can I check allotment status for Link Intime issues?
      </button>
    </div>
  `;
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
}

function formatAIMarkdown(text) {
  if (!text) return '';
  let processed = String(text);

  // Markdown headers
  processed = processed
    .replace(/^###\s*(.*)$/gm, '<div class="font-bold text-[13px] mt-2 mb-1">$1</div>')
    .replace(/^##\s*(.*)$/gm, '<div class="font-bold text-[14px] mt-2 mb-1">$1</div>')
    .replace(/^#\s*(.*)$/gm, '<div class="font-bold text-[15px] mt-2 mb-1">$1</div>');

  // Inline formatting
  processed = processed
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono text-[10px]">$1</code>');

  // Numbered lists
  processed = processed.replace(/^\s*(\d+)[\.\)]\s+(.*)$/gm, '<li class="ml-1">$2</li>');
  processed = processed.replace(/((?:<li class="ml-1">.*?<\/li>\s*)+)/gs, function(match) {
    return `<ol class="space-y-1.5 my-2 list-decimal pl-5">${match.trim()}</ol>`;
  });

  // Bullet lists
  processed = processed.replace(/^\s*[-*•]\s+(.*)$/gm, '<li class="ml-1">$1</li>');
  processed = processed.replace(/((?:<li class="ml-1">.*?<\/li>\s*)+)/gs, function(match) {
    return `<ul class="space-y-1 my-2 list-disc pl-5">${match.trim()}</ul>`;
  });

  processed = processed.replace(/\n{2,}/g, '<br/><br/>');
  processed = processed.replace(/\n/g, '<br/>');

  return processed.trim();
}

async function submitAICopilotChat(e) {
  if (e && e.preventDefault) e.preventDefault();
  const input = document.getElementById('ai-modal-input');
  if (!input) return;
  const query = input.value.trim();
  if (!query) return;

  const chatContainer = document.getElementById('ai-modal-chat-messages');
  if (!chatContainer) return;

  const welcomeBox = document.getElementById('ai-welcome-box');
  if (welcomeBox) welcomeBox.remove();
  const suggestionsBox = document.getElementById('ai-quick-suggestions-box');
  if (suggestionsBox) suggestionsBox.remove();

  // User bubble
  const userBubble = document.createElement('div');
  userBubble.className = 'flex items-start justify-end';
  userBubble.innerHTML = `
    <div class="bg-[#24211D] text-[#FAF8F5] dark:bg-indigo-600 dark:text-white rounded-[20px] rounded-br-xs px-4 py-2.5 text-xs sm:text-[13px] max-w-[85%] shadow-xs leading-relaxed">
      ${escapeHtml(query)}
    </div>
  `;
  chatContainer.appendChild(userBubble);
  input.value = '';

  // Typing indicator
  const typingIndicator = document.createElement('div');
  typingIndicator.id = 'ai-typing-indicator';
  typingIndicator.className = 'flex items-start';
  typingIndicator.innerHTML = `
    <div class="bg-[#F5EFEB] dark:bg-[#1A2234] border border-[#E8DFD5] dark:border-slate-700/60 rounded-[20px] px-4 py-3 text-xs text-[#7C7164] dark:text-slate-400 max-w-[90%] flex items-center gap-2 shadow-2xs">
      <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-amber-600 shrink-0"></i>
      <span>Analyzing live IPO data &amp; GMP metrics...</span>
    </div>
  `;
  chatContainer.appendChild(typingIndicator);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  refreshLucideIcons();

  try {
    const res = await fetch('/api/v1/ipos/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query })
    });

    const indicator = document.getElementById('ai-typing-indicator');
    if (indicator) indicator.remove();

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server returned status ${res.status}`);
    }

    const data = await res.json();
    const replyText = data.reply || "No response received.";
    const providerBadge = data.provider
      ? `<span class="inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-200/70 dark:bg-slate-700 text-slate-600 dark:text-slate-300 uppercase">${data.provider}</span>`
      : '';

    const aiBubble = document.createElement('div');
    aiBubble.className = 'flex items-start';
    aiBubble.innerHTML = `
      <div class="bg-[#F5EFEB] dark:bg-[#1A2234] border border-[#E8DFD5] dark:border-slate-700/60 rounded-[22px] px-4 py-3.5 text-xs sm:text-[13px] text-[#2D2A26] dark:text-slate-200 max-w-[92%] leading-relaxed shadow-2xs space-y-1.5">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="text-[10px] font-bold text-amber-700 dark:text-amber-400 flex items-center gap-1">
            <i data-lucide="sparkles" class="w-3 h-3"></i> IPO Copilot
          </span>
          ${providerBadge}
        </div>
        <div>${formatAIMarkdown(replyText)}</div>
      </div>
    `;
    chatContainer.appendChild(aiBubble);

    if (aiVoiceEnabled && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(replyText.replace(/[*_#`]/g, ''));
      window.speechSynthesis.speak(utterance);
    }
  } catch (err) {
    const indicator = document.getElementById('ai-typing-indicator');
    if (indicator) indicator.remove();

    const errBubble = document.createElement('div');
    errBubble.className = 'flex items-start';
    errBubble.innerHTML = `
      <div class="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 rounded-[20px] px-4 py-3 text-xs text-rose-700 dark:text-rose-300 max-w-[90%] shadow-2xs">
        ⚠️ Failed to query AI copilot: ${escapeHtml(err.message)}
      </div>
    `;
    chatContainer.appendChild(errBubble);
  } finally {
    chatContainer.scrollTop = chatContainer.scrollHeight;
    refreshLucideIcons();
  }
}

// Global Event Listeners
document.addEventListener('click', (e) => {
  if (!e.target.closest('.custom-dropdown') && !e.target.closest('#company-picker-wrapper')) {
    if (typeof closeAllDropdowns === 'function') closeAllDropdowns();
  }
  // Close modals on backdrop click
  const aiModal = document.getElementById('ai-copilot-modal');
  if (e.target === aiModal && typeof closeAICopilotModal === 'function') {
    closeAICopilotModal();
  }
  const scoreModal = document.getElementById('score-modal');
  if (e.target === scoreModal && typeof closeModal === 'function') {
    closeModal();
  }
  const loginModal = document.getElementById('login-modal');
  if (e.target === loginModal && typeof closeLoginModal === 'function') {
    closeLoginModal();
  }
  const telegramModal = document.getElementById('telegram-modal');
  if (e.target === telegramModal && typeof closeTelegramModal === 'function') {
    closeTelegramModal();
  }
  const gmpPreviewModal = document.getElementById('gmp-preview-modal');
  if (e.target === gmpPreviewModal && typeof closeGmpPreviewModal === 'function') {
    closeGmpPreviewModal();
  }
  const appModal = document.getElementById('application-modal');
  if (e.target === appModal && typeof closeApplicationModal === 'function') {
    closeApplicationModal();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (typeof isGmpPreviewOpen === 'function' && isGmpPreviewOpen()) {
      closeGmpPreviewModal();
      return;
    }
    if (typeof closeAICopilotModal === 'function') closeAICopilotModal();
    if (typeof closeModal === 'function') closeModal();
    if (typeof closeLoginModal === 'function') closeLoginModal();
    if (typeof closeTelegramModal === 'function') closeTelegramModal();
    if (typeof closeApplicationModal === 'function') closeApplicationModal();
    if (typeof closeAllDropdowns === 'function') closeAllDropdowns();
  }
});

// ==================== IPO APPLICATION TRACKER CONTROLLER ====================
let userApplications = [];
let userApplicationsSummary = null;
let currentAppFilter = 'ALL';

function isIpoTracked(ipoId) {
  return userApplications.some(a => a.ipo_id === ipoId);
}

async function loadMyApplications() {
  const token = getAuthToken();
  const signedOutEl = document.getElementById('applications-signed-out');
  const signedInEl = document.getElementById('applications-signed-in');
  const navBadge = document.getElementById('nav-apps-badge');

  if (!token) {
    userApplications = [];
    userApplicationsSummary = null;
    if (signedOutEl) signedOutEl.classList.remove('hidden');
    if (signedInEl) signedInEl.classList.add('hidden');
    if (navBadge) navBadge.classList.add('hidden');
    if (typeof renderIpos === 'function' && Array.isArray(allIpos) && allIpos.length > 0) {
      renderIpos();
    }
    refreshLucideIcons();
    return;
  }

  if (signedOutEl) signedOutEl.classList.add('hidden');
  if (signedInEl) signedInEl.classList.remove('hidden');

  try {
    const res = await fetch('/api/v1/applications', {
      headers: getAuthHeaders()
    });
    if (res.status === 401) {
      setAuthToken(null);
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    userApplications = data.items || [];
    userApplicationsSummary = data.summary || {};

    if (navBadge) {
      if (userApplications.length > 0) {
        navBadge.textContent = userApplications.length;
        navBadge.classList.remove('hidden');
      } else {
        navBadge.classList.add('hidden');
      }
    }

    renderApplicationsSummary(userApplicationsSummary);
    renderApplicationsList();
    if (typeof renderIpos === 'function' && Array.isArray(allIpos) && allIpos.length > 0) {
      renderIpos();
    }
  } catch (err) {
    console.warn('Failed to load user applications:', err);
  }
}

function formatInrCompact(val) {
  const n = Number(val || 0);
  const sign = n < 0 ? '-' : '';
  return sign + '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function renderApplicationsSummary(s) {
  if (!s) return;
  const blockedEl = document.getElementById('app-stat-blocked');
  const activeSubEl = document.getElementById('app-stat-active-sub');
  const hitRatioEl = document.getElementById('app-stat-hit-ratio');
  const hitSubEl = document.getElementById('app-stat-hit-sub');
  const realizedEl = document.getElementById('app-stat-realized');
  const expectedEl = document.getElementById('app-stat-expected');

  if (blockedEl) blockedEl.textContent = formatInrCompact(s.active_blocked_capital);
  if (activeSubEl) activeSubEl.textContent = `${s.active_applications || 0} active bid${s.active_applications === 1 ? '' : 's'} · ${s.total_applications || 0} total`;
  if (hitRatioEl) hitRatioEl.textContent = `${Number(s.hit_ratio_pct || 0).toFixed(1)}%`;
  if (hitSubEl) hitSubEl.textContent = `${s.allotted_count || 0} / ${s.decided_count || 0} allotted`;

  if (realizedEl) {
    const r = Number(s.total_realized_profit || 0);
    realizedEl.textContent = (r > 0 ? '+' : '') + formatInrCompact(r);
    realizedEl.className = `text-xl sm:text-2xl font-bold font-mono mt-0.5 tabular-nums ${r > 0 ? 'text-emerald-600 dark:text-emerald-400' : r < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-slate-900 dark:text-white'}`;
  }
  if (expectedEl) {
    const e = Number(s.expected_gmp_profit || 0);
    expectedEl.textContent = (e > 0 ? '+' : '') + formatInrCompact(e);
  }
}

function filterApplications(filter) {
  currentAppFilter = filter;
  ['ALL', 'APPLIED', 'ALLOTTED', 'NOT_ALLOTTED', 'SOLD'].forEach(f => {
    const btn = document.getElementById('app-filter-' + f);
    if (!btn) return;
    if (f === filter) {
      btn.className = 'px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 text-white transition cursor-pointer';
    } else {
      btn.className = 'px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer';
    }
  });
  renderApplicationsList();
}

function renderApplicationsList() {
  const container = document.getElementById('applications-list-container');
  if (!container) return;

  const filtered = currentAppFilter === 'ALL'
    ? userApplications
    : userApplications.filter(a => a.status === currentAppFilter);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="bg-white dark:bg-[#121826] p-8 rounded-xl border border-[#E8EAEE] dark:border-[#1F2937] text-center space-y-2">
        <p class="text-sm font-bold text-slate-700 dark:text-slate-300">No IPO applications logged yet</p>
        <p class="text-xs text-slate-500 dark:text-slate-400">Click <strong>+ Track</strong> on any IPO card or click <strong>Log IPO Application</strong> above to start tracking your bids and listing gains.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(item => {
    let statusBadge = '';
    if (item.status === 'APPLIED') {
      statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">APPLIED</span>';
    } else if (item.status === 'ALLOTTED') {
      statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">ALLOTTED</span>';
    } else if (item.status === 'SOLD') {
      statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-50 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">SOLD</span>';
    } else {
      statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">NOT ALLOTTED</span>';
    }

    const profitVal = item.realized_profit !== null && item.realized_profit !== undefined ? item.realized_profit : item.estimated_profit;
    const isRealized = item.realized_profit !== null && item.realized_profit !== undefined;
    const profitColor = profitVal > 0 ? 'text-emerald-600 dark:text-emerald-400' : profitVal < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-slate-500 dark:text-slate-400';
    const profitLabel = item.status === 'NOT_ALLOTTED'
      ? '₹0 (Refunded)'
      : `${profitVal > 0 ? '+' : ''}${formatInrCompact(profitVal)} (${item.profit_pct > 0 ? '+' : ''}${Number(item.profit_pct || 0).toFixed(1)}%) ${isRealized ? '· Realized' : '· Est. GMP'}`;

    const quickActions = item.status === 'APPLIED'
      ? `
        <button onclick="quickUpdateApplicationStatus(${item.id}, 'ALLOTTED')" class="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 hover:bg-emerald-100 transition cursor-pointer">✓ Mark Allotted</button>
        <button onclick="quickUpdateApplicationStatus(${item.id}, 'NOT_ALLOTTED')" class="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 transition cursor-pointer">✕ Not Allotted</button>
      `
      : '';

    return `
      <div class="bg-white dark:bg-[#121826] p-4 rounded-xl border border-[#E8EAEE] dark:border-[#1F2937] shadow-soft flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div class="space-y-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${escapeHtml(item.symbol)}</span>
            <h4 class="text-sm font-bold text-slate-900 dark:text-white">${escapeHtml(item.company_name)}</h4>
            ${statusBadge}
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300">${escapeHtml(item.applicant_name)} · ${escapeHtml(item.category)}</span>
          </div>
          <div class="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400 flex-wrap font-mono">
            <span>Lots: <strong>${item.lots_applied}</strong> (${item.shares_applied} sh @ ₹${item.bid_price})</span>
            <span>Blocked: <strong class="text-slate-800 dark:text-slate-200">${formatInrCompact(item.amount_blocked)}</strong></span>
            ${item.selling_price ? `<span>Exit: <strong>₹${item.selling_price}</strong></span>` : ''}
            <span class="font-bold ${profitColor}">${profitLabel}</span>
          </div>
          ${item.notes ? `<p class="text-[11px] text-slate-400 italic">${escapeHtml(item.notes)}</p>` : ''}
        </div>
        <div class="flex items-center gap-1.5 shrink-0 flex-wrap">
          ${quickActions}
          <button onclick="openApplicationModal(${item.id})" class="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer">Edit</button>
          <button onclick="deleteUserApplication(${item.id})" class="px-2 py-1 rounded-lg text-[11px] font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/50 transition cursor-pointer">Delete</button>
        </div>
      </div>
    `;
  }).join('');
  refreshLucideIcons();
}

function openTrackApplicationForIpo(ipoId) {
  if (!getAuthToken()) {
    openLoginModal('signin');
    return;
  }
  openApplicationModal(null, ipoId);
}

function openApplicationModal(editAppId = null, prefillIpoId = null) {
  if (!getAuthToken()) {
    openLoginModal('signin');
    return;
  }
  const modal = document.getElementById('application-modal');
  const titleEl = document.getElementById('app-modal-title');
  const idInput = document.getElementById('app-form-id');
  const ipoSelect = document.getElementById('app-form-ipo');
  const applicantInput = document.getElementById('app-form-applicant');
  const catSelect = document.getElementById('app-form-category');
  const lotsInput = document.getElementById('app-form-lots');
  const priceInput = document.getElementById('app-form-price');
  const statusSelect = document.getElementById('app-form-status');
  const lotsAllottedInput = document.getElementById('app-form-lots-allotted');
  const sellingPriceInput = document.getElementById('app-form-selling-price');
  const notesInput = document.getElementById('app-form-notes');
  const errEl = document.getElementById('app-form-error');

  if (errEl) { errEl.classList.add('hidden'); errEl.textContent = ''; }

  // Populate IPO dropdown
  if (ipoSelect && Array.isArray(allIpos)) {
    ipoSelect.innerHTML = allIpos.map(i => {
      const p = i.issue_price || i.price_band_high || i.price_band_low || 100;
      return `<option value="${i.id}" data-price="${p}" data-lot="${i.lot_size || 1}">${escapeHtml(i.company_name)} (${escapeHtml(i.symbol)} · ${i.status})</option>`;
    }).join('');
  }

  if (editAppId) {
    const existing = userApplications.find(a => a.id === editAppId);
    if (!existing) return;
    if (titleEl) titleEl.textContent = 'Edit IPO Application';
    idInput.value = String(existing.id);
    if (ipoSelect) {
      ipoSelect.value = String(existing.ipo_id);
      ipoSelect.disabled = true;
    }
    applicantInput.value = existing.applicant_name || 'Self';
    catSelect.value = existing.category || 'RETAIL';
    lotsInput.value = existing.lots_applied || 1;
    priceInput.value = existing.bid_price || 100;
    statusSelect.value = existing.status || 'APPLIED';
    lotsAllottedInput.value = existing.lots_allotted || 1;
    sellingPriceInput.value = existing.selling_price || '';
    notesInput.value = existing.notes || '';
  } else {
    if (titleEl) titleEl.textContent = 'Log IPO Application';
    idInput.value = '';
    if (ipoSelect) {
      ipoSelect.disabled = false;
      if (prefillIpoId) ipoSelect.value = String(prefillIpoId);
    }
    applicantInput.value = 'Self';
    catSelect.value = 'RETAIL';
    lotsInput.value = 1;
    statusSelect.value = 'APPLIED';
    lotsAllottedInput.value = 1;
    sellingPriceInput.value = '';
    notesInput.value = '';
    onAppModalIpoChange();
  }

  onAppModalStatusChange();
  updateAppModalBlockedPreview();
  if (modal) modal.classList.remove('hidden');
  refreshLucideIcons();
}

function closeApplicationModal() {
  const modal = document.getElementById('application-modal');
  if (modal) modal.classList.add('hidden');
}

function onAppModalIpoChange() {
  const ipoSelect = document.getElementById('app-form-ipo');
  const priceInput = document.getElementById('app-form-price');
  if (!ipoSelect || !priceInput) return;
  const opt = ipoSelect.options[ipoSelect.selectedIndex];
  if (opt) {
    priceInput.value = opt.getAttribute('data-price') || 100;
  }
  updateAppModalBlockedPreview();
}

function onAppModalStatusChange() {
  const statusSelect = document.getElementById('app-form-status');
  const allottedWrap = document.getElementById('app-form-allotted-wrap');
  const exitWrap = document.getElementById('app-form-exit-wrap');
  if (!statusSelect) return;
  const st = statusSelect.value;
  if (st === 'ALLOTTED' || st === 'SOLD') {
    if (allottedWrap) allottedWrap.classList.remove('hidden');
    if (exitWrap) exitWrap.classList.remove('hidden');
  } else {
    if (allottedWrap) allottedWrap.classList.add('hidden');
    if (exitWrap) exitWrap.classList.add('hidden');
  }
}

function updateAppModalBlockedPreview() {
  const ipoSelect = document.getElementById('app-form-ipo');
  const lotsInput = document.getElementById('app-form-lots');
  const priceInput = document.getElementById('app-form-price');
  const previewEl = document.getElementById('app-form-blocked-preview');
  if (!ipoSelect || !lotsInput || !priceInput || !previewEl) return;

  const opt = ipoSelect.options[ipoSelect.selectedIndex];
  const lotSize = opt ? Number(opt.getAttribute('data-lot') || 1) : 1;
  const lots = Number(lotsInput.value || 1);
  const price = Number(priceInput.value || 0);
  const shares = lots * lotSize;
  const blocked = shares * price;
  previewEl.textContent = `${formatInrCompact(blocked)} (${shares} shares)`;
}

async function submitApplicationForm(e) {
  if (e && e.preventDefault) e.preventDefault();
  const idVal = document.getElementById('app-form-id').value;
  const ipoId = Number(document.getElementById('app-form-ipo').value);
  const applicant = document.getElementById('app-form-applicant').value.trim() || 'Self';
  const category = document.getElementById('app-form-category').value;
  const lots = Number(document.getElementById('app-form-lots').value || 1);
  const price = Number(document.getElementById('app-form-price').value || 0);
  const statusVal = document.getElementById('app-form-status').value;
  const lotsAllotted = Number(document.getElementById('app-form-lots-allotted').value || 0);
  const sellingPriceRaw = document.getElementById('app-form-selling-price').value;
  const sellingPrice = sellingPriceRaw ? Number(sellingPriceRaw) : null;
  const notes = document.getElementById('app-form-notes').value.trim();
  const errEl = document.getElementById('app-form-error');

  const payload = {
    ipo_id: ipoId,
    applicant_name: applicant,
    category: category,
    lots_applied: lots,
    bid_price: price,
    status: statusVal,
    lots_allotted: (statusVal === 'ALLOTTED' || statusVal === 'SOLD') ? Math.max(1, lotsAllotted) : 0,
    selling_price: sellingPrice,
    notes: notes || null
  };

  try {
    const url = idVal ? `/api/v1/applications/${idVal}` : '/api/v1/applications';
    const method = idVal ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method: method,
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to save application');
    }
    closeApplicationModal();
    await loadMyApplications();
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  }
}

async function quickUpdateApplicationStatus(appId, newStatus) {
  try {
    const res = await fetch(`/api/v1/applications/${appId}`, {
      method: 'PUT',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ status: newStatus })
    });
    if (res.ok) {
      await loadMyApplications();
    }
  } catch (err) {
    console.warn('Quick status update error:', err);
  }
}

async function deleteUserApplication(appId) {
  try {
    const res = await fetch(`/api/v1/applications/${appId}`, {
      method: 'DELETE',
      headers: getAuthHeaders()
    });
    if (res.ok) {
      await loadMyApplications();
    }
  } catch (err) {
    console.warn('Delete application error:', err);
  }
}

// App Bootstrap
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  updateAuthUI();
  const hash = window.location.hash.replace('#', '');
  if (['ipos', 'allotment', 'applications', 'methodology'].includes(hash)) {
    switchTab(hash);
  } else {
    switchTab('ipos');
  }
  loadRegistrarCompanies();
  loadScoringMethodology();
  loadIpos();
  loadMyApplications();
  initLiveSync();
  refreshLucideIcons();
});
