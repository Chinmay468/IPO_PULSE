// ==================== AUTH & TELEGRAM MANAGEMENT ====================

function getAuthToken() {
  return localStorage.getItem('ipo_pulse_token') || '';
}

function setAuthToken(token) {
  if (token) {
    localStorage.setItem('ipo_pulse_token', token);
  } else {
    localStorage.removeItem('ipo_pulse_token');
  }
  updateAuthUI();
}

function getAuthHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

function updateAuthUI() {
  const token = getAuthToken();
  const label = document.getElementById('auth-header-label');
  const icon = document.getElementById('auth-header-icon');
  const btn = document.getElementById('auth-header-btn');
  if (token) {
    if (label) label.textContent = 'Admin (Logout)';
    if (icon) icon.setAttribute('data-lucide', 'unlock');
    if (btn) btn.classList.add('border-emerald-500/50', 'text-emerald-600', 'dark:text-emerald-400');
  } else {
    if (label) label.textContent = 'Sign In';
    if (icon) icon.setAttribute('data-lucide', 'lock');
    if (btn) btn.classList.remove('border-emerald-500/50', 'text-emerald-600', 'dark:text-emerald-400');
  }
  refreshLucideIcons();
}

function openLoginModal() {
  const modal = document.getElementById('login-modal');
  const err = document.getElementById('login-error');
  if (err) { err.classList.add('hidden'); err.textContent = ''; }
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  refreshLucideIcons();
}

function closeLoginModal() {
  const modal = document.getElementById('login-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

function handleAuthButtonClick() {
  if (getAuthToken()) {
    if (confirm('Log out from Admin session?')) {
      setAuthToken(null);
      if (typeof resetPortfolioUI === 'function') resetPortfolioUI(true);
      if (typeof resetMFUI === 'function') resetMFUI();
    }
  } else {
    openLoginModal();
  }
}

async function submitLogin(e) {
  e.preventDefault();
  const user = document.getElementById('login-username').value.trim();
  const pass = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  const spinner = document.getElementById('login-spinner');
  const submitText = document.getElementById('login-submit-text');
  const submitBtn = document.getElementById('login-submit-btn');

  errEl.classList.add('hidden');
  spinner.classList.remove('hidden');
  submitText.textContent = 'Verifying...';
  submitBtn.disabled = true;

  try {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass })
    });
    if (res.status === 429) {
      throw new Error('Too many login attempts. Please wait 1 minute.');
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Invalid username or password.');
    }
    const data = await res.json();
    setAuthToken(data.access_token);
    closeLoginModal();
    document.getElementById('login-password').value = '';
    if (typeof loadPortfolio === 'function') await loadPortfolio();
    if (typeof loadMFSummary === 'function') await loadMFSummary();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    spinner.classList.add('hidden');
    submitText.textContent = 'Sign In';
    submitBtn.disabled = false;
    refreshLucideIcons();
  }
}

// ==================== TELEGRAM NOTIFICATIONS ====================

async function openTelegramModal() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const modal = document.getElementById('telegram-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  const msgBox = document.getElementById('tg-alert-msg');
  if (msgBox) {
    msgBox.classList.add('hidden');
    msgBox.textContent = '';
  }
  refreshLucideIcons();
  await fetchTelegramStatus();
}

function closeTelegramModal() {
  const modal = document.getElementById('telegram-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

async function fetchTelegramStatus() {
  const badge = document.getElementById('tg-status-badge');
  const chatIdEl = document.getElementById('tg-chat-id');
  const minScoreEl = document.getElementById('tg-min-score');
  const minGmpEl = document.getElementById('tg-min-gmp');
  try {
    const res = await fetch('/api/v1/telegram/status', { headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      if (typeof resetPortfolioUI === 'function') resetPortfolioUI(true);
      closeTelegramModal();
      openLoginModal();
      return;
    }
    if (!res.ok) throw new Error('Failed to load status');
    const data = await res.json();
    if (data.configured) {
      badge.textContent = 'Active & Connected';
      badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800';
    } else {
      badge.textContent = 'Not Configured (.env)';
      badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 dark:bg-rose-950/60 text-rose-700 dark:text-rose-400 border border-rose-300 dark:border-rose-800';
    }
    const targetSegEl = document.getElementById('tg-target-segment');
    if (targetSegEl) targetSegEl.textContent = data.mainboard_only ? 'Mainboard Only (~₹15k)' : 'All (Mainboard & SME)';
    if (chatIdEl) chatIdEl.textContent = data.chat_id_masked || 'Not Set';
    if (minScoreEl) minScoreEl.textContent = `${data.min_score}+ (STRONG_APPLY)`;
    if (minGmpEl) minGmpEl.textContent = `+${data.min_gmp_pct}%`;
  } catch (e) {
    if (badge) {
      badge.textContent = 'Error checking status';
      badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-700';
    }
  }
}

function showTelegramNotice(msg, isSuccess = true) {
  const el = document.getElementById('tg-alert-msg');
  if (!el) return;
  el.textContent = msg;
  el.className = isSuccess
    ? 'p-3 rounded-xl text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
    : 'p-3 rounded-xl text-xs font-semibold bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-300';
  el.classList.remove('hidden');
}

async function triggerTelegramTest() {
  const btn = document.getElementById('tg-test-btn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Testing...';
  refreshLucideIcons();
  try {
    const res = await fetch('/api/v1/telegram/test', { method: 'POST', headers: getAuthHeaders() });
    const data = await res.json();
    if (res.ok) {
      showTelegramNotice('✅ Test alert dispatched to your Telegram chat successfully!', true);
    } else {
      showTelegramNotice('❌ ' + (data.detail || 'Failed to dispatch test notification.'), false);
    }
  } catch (e) {
    showTelegramNotice('❌ Network error: ' + e.message, false);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
    refreshLucideIcons();
  }
}

async function triggerTelegramDigest() {
  const btn = document.getElementById('tg-digest-btn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Sending...';
  refreshLucideIcons();
  try {
    const res = await fetch('/api/v1/telegram/digest', { method: 'POST', headers: getAuthHeaders() });
    const data = await res.json();
    if (res.ok) {
      showTelegramNotice('✅ Top picks digest sent to Telegram! (' + (data.picks_count || 0) + ' picks)', true);
    } else {
      showTelegramNotice('❌ ' + (data.detail || 'Failed to send digest.'), false);
    }
  } catch (e) {
    showTelegramNotice('❌ Network error: ' + e.message, false);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
    refreshLucideIcons();
  }
}

async function triggerTelegramBroadcast() {
  const btn = document.getElementById('tg-broadcast-btn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Broadcasting...';
  refreshLucideIcons();
  try {
    const res = await fetch('/api/v1/telegram/broadcast-best', { method: 'POST', headers: getAuthHeaders() });
    const data = await res.json();
    if (res.ok) {
      showTelegramNotice(`✅ Scan complete: ${data.sent || 0} alert(s) sent, ${data.skipped || 0} skipped.`, true);
    } else {
      showTelegramNotice('❌ ' + (data.detail || 'Failed to broadcast alerts.'), false);
    }
  } catch (e) {
    showTelegramNotice('❌ Network error: ' + e.message, false);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
    refreshLucideIcons();
  }
}
