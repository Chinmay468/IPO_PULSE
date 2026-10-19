// ==================== AUTH & TELEGRAM MANAGEMENT ====================

function getAuthToken() {
  return localStorage.getItem('ipo_pulse_token') || '';
}

function getAuthUser() {
  return localStorage.getItem('ipo_pulse_username') || 'User';
}

function setAuthToken(token, username = null) {
  if (token) {
    localStorage.setItem('ipo_pulse_token', token);
    if (username) {
      localStorage.setItem('ipo_pulse_username', username);
    }
  } else {
    localStorage.removeItem('ipo_pulse_token');
    localStorage.removeItem('ipo_pulse_username');
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
  const menuLabel = document.getElementById('menu-auth-label');
  if (token) {
    const user = getAuthUser();
    if (label) label.textContent = `${user} (Logout)`;
    if (menuLabel) menuLabel.textContent = `${user} (Logout)`;
    if (icon) icon.setAttribute('data-lucide', 'unlock');
    if (btn) btn.classList.add('border-emerald-500/50', 'text-emerald-600', 'dark:text-emerald-400');
  } else {
    if (label) label.textContent = 'Sign In';
    if (menuLabel) menuLabel.textContent = 'Sign In / Register';
    if (icon) icon.setAttribute('data-lucide', 'lock');
    if (btn) btn.classList.remove('border-emerald-500/50', 'text-emerald-600', 'dark:text-emerald-400');
  }
  refreshLucideIcons();
}

function switchAuthTab(tab) {
  const signinForm = document.getElementById('login-form');
  const signupForm = document.getElementById('register-form');
  const signinBtn = document.getElementById('tab-btn-signin');
  const signupBtn = document.getElementById('tab-btn-signup');
  const modalTitle = document.getElementById('login-modal-title');
  const modalSub = document.getElementById('login-modal-subtitle');
  const errEl = document.getElementById('login-error');
  const succEl = document.getElementById('login-success');

  if (errEl) { errEl.classList.add('hidden'); errEl.textContent = ''; }
  if (succEl) { succEl.classList.add('hidden'); succEl.textContent = ''; }
  const userFeedback = document.getElementById('register-username-feedback');
  const userSpinner = document.getElementById('register-username-spinner');
  const userInput = document.getElementById('register-username');
  if (userFeedback) { userFeedback.classList.add('hidden'); userFeedback.innerHTML = ''; }
  if (userSpinner) userSpinner.classList.add('hidden');
  if (userInput) userInput.classList.remove('border-rose-500', 'focus:ring-rose-500', 'border-emerald-500', 'focus:ring-emerald-500');
  isUsernameAvailable = null;

  const activeClasses = ['text-blue-600', 'dark:text-blue-400', 'bg-white', 'dark:bg-slate-800', 'shadow-sm', 'border', 'border-slate-200/60', 'dark:border-slate-700/60'];
  const inactiveClasses = ['text-slate-500', 'hover:text-slate-800', 'dark:text-slate-400', 'dark:hover:text-slate-200'];

  if (tab === 'signup') {
    if (signinForm) signinForm.classList.add('hidden');
    if (signupForm) signupForm.classList.remove('hidden');
    if (modalTitle) modalTitle.textContent = 'Create New Account';
    if (modalSub) modalSub.textContent = 'Sign up to build and manage your portfolio';

    if (signupBtn) {
      signupBtn.classList.remove(...inactiveClasses);
      signupBtn.classList.add(...activeClasses);
    }
    if (signinBtn) {
      signinBtn.classList.remove(...activeClasses);
      signinBtn.classList.add(...inactiveClasses);
    }
  } else {
    if (signupForm) signupForm.classList.add('hidden');
    if (signinForm) signinForm.classList.remove('hidden');
    if (modalTitle) modalTitle.textContent = 'Account Access';
    if (modalSub) modalSub.textContent = 'Sign in to manage your portfolio';

    if (signinBtn) {
      signinBtn.classList.remove(...inactiveClasses);
      signinBtn.classList.add(...activeClasses);
    }
    if (signupBtn) {
      signupBtn.classList.remove(...activeClasses);
      signupBtn.classList.add(...inactiveClasses);
    }
  }
  refreshLucideIcons();
}

function openLoginModal(tab = 'signin') {
  const modal = document.getElementById('login-modal');
  switchAuthTab(tab);
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
    const user = getAuthUser();
    if (confirm(`Log out from ${user}'s session?`)) {
      setAuthToken(null);
      if (typeof resetPortfolioUI === 'function') resetPortfolioUI(true);
      if (typeof resetMFUI === 'function') resetMFUI();
      if (typeof resetCombinedNetWorthUI === 'function') resetCombinedNetWorthUI(true);
    }
  } else {
    openLoginModal('signin');
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
    setAuthToken(data.access_token, data.username || user);
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

let usernameCheckTimer = null;
let isUsernameAvailable = null;

function handleUsernameInput(event) {
  const input = event.target;
  const username = input.value.trim();
  const feedbackEl = document.getElementById('register-username-feedback');
  const spinnerEl = document.getElementById('register-username-spinner');

  if (usernameCheckTimer) clearTimeout(usernameCheckTimer);

  if (!username) {
    isUsernameAvailable = null;
    if (feedbackEl) { feedbackEl.classList.add('hidden'); feedbackEl.innerHTML = ''; }
    if (spinnerEl) spinnerEl.classList.add('hidden');
    input.classList.remove('border-rose-500', 'focus:ring-rose-500', 'border-emerald-500', 'focus:ring-emerald-500');
    return;
  }

  if (username.length < 3) {
    isUsernameAvailable = false;
    input.classList.remove('border-emerald-500', 'focus:ring-emerald-500');
    input.classList.add('border-rose-500', 'focus:ring-rose-500');
    if (spinnerEl) spinnerEl.classList.add('hidden');
    if (feedbackEl) {
      feedbackEl.className = 'text-[11px] mt-1 font-medium text-rose-600 dark:text-rose-400 flex items-center gap-1';
      feedbackEl.innerHTML = '<i data-lucide="alert-circle" class="w-3 h-3"></i> Must be at least 3 characters.';
      feedbackEl.classList.remove('hidden');
    }
    refreshLucideIcons();
    return;
  }

  const pattern = /^[a-zA-Z0-9_.-]+$/;
  if (!pattern.test(username)) {
    isUsernameAvailable = false;
    input.classList.remove('border-emerald-500', 'focus:ring-emerald-500');
    input.classList.add('border-rose-500', 'focus:ring-rose-500');
    if (spinnerEl) spinnerEl.classList.add('hidden');
    if (feedbackEl) {
      feedbackEl.className = 'text-[11px] mt-1 font-medium text-rose-600 dark:text-rose-400 flex items-center gap-1';
      feedbackEl.innerHTML = '<i data-lucide="alert-circle" class="w-3 h-3"></i> Only letters, numbers, _, -, and . allowed.';
      feedbackEl.classList.remove('hidden');
    }
    refreshLucideIcons();
    return;
  }

  if (spinnerEl) spinnerEl.classList.remove('hidden');
  if (feedbackEl) {
    feedbackEl.className = 'text-[11px] mt-1 font-medium text-slate-400 flex items-center gap-1';
    feedbackEl.innerHTML = '<span>Checking availability...</span>';
    feedbackEl.classList.remove('hidden');
  }

  usernameCheckTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/v1/auth/check-username?username=${encodeURIComponent(username)}`);
      if (!res.ok) throw new Error('Could not verify username.');
      const data = await res.json();

      // Ensure input hasn't changed while awaiting response
      if (document.getElementById('register-username').value.trim() !== username) return;

      if (data.available) {
        isUsernameAvailable = true;
        input.classList.remove('border-rose-500', 'focus:ring-rose-500');
        input.classList.add('border-emerald-500', 'focus:ring-emerald-500');
        if (feedbackEl) {
          feedbackEl.className = 'text-[11px] mt-1 font-medium text-emerald-600 dark:text-emerald-400 flex items-center gap-1';
          feedbackEl.innerHTML = '<i data-lucide="check-circle-2" class="w-3 h-3"></i> Username is available!';
          feedbackEl.classList.remove('hidden');
        }
      } else {
        isUsernameAvailable = false;
        input.classList.remove('border-emerald-500', 'focus:ring-emerald-500');
        input.classList.add('border-rose-500', 'focus:ring-rose-500');
        if (feedbackEl) {
          feedbackEl.className = 'text-[11px] mt-1 font-medium text-rose-600 dark:text-rose-400 flex items-center gap-1';
          feedbackEl.innerHTML = `<i data-lucide="x-circle" class="w-3 h-3"></i> ${data.message || 'Username is already taken.'}`;
          feedbackEl.classList.remove('hidden');
        }
      }
    } catch (err) {
      console.warn('Username check failed:', err);
    } finally {
      if (spinnerEl) spinnerEl.classList.add('hidden');
      refreshLucideIcons();
    }
  }, 300);
}

async function submitRegister(e) {
  e.preventDefault();
  const username = document.getElementById('register-username').value.trim();
  const email = (document.getElementById('register-email').value || '').trim();
  const password = document.getElementById('register-password').value;
  const confirmPassword = document.getElementById('register-confirm-password').value;
  const errEl = document.getElementById('login-error');
  const succEl = document.getElementById('login-success');
  const spinner = document.getElementById('register-spinner');
  const submitText = document.getElementById('register-submit-text');
  const submitBtn = document.getElementById('register-submit-btn');

  errEl.classList.add('hidden');
  succEl.classList.add('hidden');

  if (isUsernameAvailable === false) {
    errEl.textContent = 'Please choose an available username before creating an account.';
    errEl.classList.remove('hidden');
    document.getElementById('register-username').focus();
    return;
  }

  if (password !== confirmPassword) {
    errEl.textContent = 'Passwords do not match. Please verify and try again.';
    errEl.classList.remove('hidden');
    return;
  }

  if (password.length < 6) {
    errEl.textContent = 'Password must be at least 6 characters long.';
    errEl.classList.remove('hidden');
    return;
  }

  spinner.classList.remove('hidden');
  submitText.textContent = 'Creating Account...';
  submitBtn.disabled = true;

  try {
    const payload = { username, password };
    if (email) payload.email = email;

    const res = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.status === 429) {
      throw new Error('Too many registration attempts. Please wait 1 minute.');
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to register account.');
    }

    const data = await res.json();
    setAuthToken(data.access_token, data.username || username);
    succEl.textContent = 'Account created successfully! Welcome to IPO Pulse.';
    succEl.classList.remove('hidden');

    setTimeout(async () => {
      closeLoginModal();
      document.getElementById('register-password').value = '';
      document.getElementById('register-confirm-password').value = '';
      if (typeof loadPortfolio === 'function') await loadPortfolio();
      if (typeof loadMFSummary === 'function') await loadMFSummary();
    }, 700);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    spinner.classList.add('hidden');
    submitText.textContent = 'Create Account';
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
