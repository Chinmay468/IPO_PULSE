// ==================== MAIN APPLICATION CONTROLLER ====================

// Tab Switching
function switchTab(tabId) {
  currentActiveTab = tabId;
  document.querySelectorAll('main > section').forEach(sec => sec.classList.add('hidden'));
  const activeSection = document.getElementById('tab-' + tabId);
  if (activeSection) activeSection.classList.remove('hidden');

  // Update Desktop and Mobile Tabs
  ['ipos', 'allotment', 'methodology'].forEach(t => {
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
    if (typeof closeAllDropdowns === 'function') closeAllDropdowns();
  }
});

// App Bootstrap
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  updateAuthUI();
  const hash = window.location.hash.replace('#', '');
  if (['ipos', 'allotment', 'methodology'].includes(hash)) {
    switchTab(hash);
  } else {
    switchTab('ipos');
  }
  loadRegistrarCompanies();
  loadScoringMethodology();
  loadIpos();
  initLiveSync();
  refreshLucideIcons();
});
