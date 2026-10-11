// ==================== MAIN APPLICATION CONTROLLER ====================

// Tab Switching
function switchTab(tabId) {
  currentActiveTab = tabId;
  document.querySelectorAll('main > section').forEach(sec => sec.classList.add('hidden'));
  const activeSection = document.getElementById('tab-' + tabId);
  if (activeSection) activeSection.classList.remove('hidden');

  // Update Desktop and Mobile Tabs
  ['portfolio', 'mf', 'ipos', 'allotment', 'methodology'].forEach(t => {
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
  if (tabId === 'portfolio') loadPortfolio();
  if (tabId === 'mf') loadMFSummary();
  if (tabId === 'methodology') loadScoringMethodology();
  if (tabId === 'ipos') loadIpos();
  refreshLucideIcons();
}

function openAICopilot() {
  toggleAICopilotModal();
}

// 15s Live Sync Controller
function initLiveSync() {
  if (liveSyncInterval) clearInterval(liveSyncInterval);
  liveSyncInterval = setInterval(() => {
    if (!liveSyncEnabled) return;
    if (currentActiveTab === 'portfolio') {
      if (!getAuthToken()) return;
      loadPortfolio(true);
    } else if (currentActiveTab === 'mf') {
      if (!getAuthToken()) return;
      loadMFSummary(true);
    } else if (currentActiveTab === 'ipos') {
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
    if (currentActiveTab === 'portfolio') {
      if (getAuthToken()) loadPortfolio(true);
    } else if (currentActiveTab === 'mf') {
      if (getAuthToken()) loadMFSummary(true);
    } else if (currentActiveTab === 'ipos') {
      loadIpos(true);
    }
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
      resetPortfolioUI(true);
      openLoginModal();
      return;
    }
    await loadIpos();
    if (currentActiveTab === 'portfolio') await loadPortfolio();
  } catch (err) {
    console.error("Sync error:", err);
  } finally {
    if (icon) icon.classList.remove('animate-spin');
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
  const addModal = document.getElementById('add-holding-modal');
  if (e.target === addModal && typeof closeAddHoldingModal === 'function') {
    closeAddHoldingModal();
  }
  const aoDiagModal = document.getElementById('angelone-diag-modal');
  if (e.target === aoDiagModal && typeof closeAngelOneDiagModal === 'function') {
    closeAngelOneDiagModal();
  }
  const mfCasModal = document.getElementById('mf-cas-modal');
  if (e.target === mfCasModal && typeof closeMFCASModal === 'function') {
    closeMFCASModal();
  }
  const mfManualModal = document.getElementById('mf-manual-modal');
  if (e.target === mfManualModal && typeof closeMFManualModal === 'function') {
    closeMFManualModal();
  }
  const loginModal = document.getElementById('login-modal');
  if (e.target === loginModal && typeof closeLoginModal === 'function') {
    closeLoginModal();
  }
  const telegramModal = document.getElementById('telegram-modal');
  if (e.target === telegramModal && typeof closeTelegramModal === 'function') {
    closeTelegramModal();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (typeof closeAICopilotModal === 'function') closeAICopilotModal();
    if (typeof closeModal === 'function') closeModal();
    if (typeof closeAddHoldingModal === 'function') closeAddHoldingModal();
    if (typeof closeAngelOneDiagModal === 'function') closeAngelOneDiagModal();
    if (typeof closeMFCASModal === 'function') closeMFCASModal();
    if (typeof closeMFManualModal === 'function') closeMFManualModal();
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
  if (['portfolio', 'mf', 'ipos', 'allotment', 'methodology'].includes(hash)) {
    switchTab(hash);
  } else {
    loadPortfolio(!getAuthToken());
  }
  loadCombinedNetWorth();
  loadRegistrarCompanies();
  loadScoringMethodology();
  loadIpos();
  initLiveSync();
  refreshLucideIcons();
});
