// ==================== TECHNICAL ADVISORY & AI COPILOT ====================

let aiVoiceEnabled = false;

function openAICopilot() {
  openAICopilotModal();
}

function formatAIMarkdown(text) {
  if (!text) return '';
  let processed = String(text);

  // Handle Markdown Tables if present
  if (processed.includes('|')) {
    const lines = processed.split('\n');
    let inTable = false;
    let tableHtml = '';
    let newLines = [];
    for (let line of lines) {
      if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
        if (!inTable) {
          inTable = true;
          tableHtml = '<div class="overflow-x-auto my-2"><table class="w-full text-[11px] border border-[#DFD6CB] dark:border-slate-700/80 rounded-lg overflow-hidden"><tbody class="divide-y divide-[#EAE3DA] dark:divide-slate-800">';
        }
        if (line.includes('---')) continue;
        const cells = line.split('|').filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
        tableHtml += '<tr class="hover:bg-[#F2ECE3] dark:hover:bg-slate-800/50">';
        cells.forEach(c => {
          tableHtml += `<td class="px-2 py-1 border-r border-[#EAE3DA] dark:border-slate-800/60 last:border-r-0">${c.trim()}</td>`;
        });
        tableHtml += '</tr>';
      } else {
        if (inTable) {
          inTable = false;
          tableHtml += '</tbody></table></div>';
          newLines.push(tableHtml);
        }
        newLines.push(line);
      }
    }
    if (inTable) {
      tableHtml += '</tbody></table></div>';
      newLines.push(tableHtml);
    }
    processed = newLines.join('\n');
  }

  // Strip / clean markdown headers
  processed = processed
    .replace(/^###\s*(.*)$/gm, '<div class="font-bold text-[13px] mt-2 mb-1">$1</div>')
    .replace(/^##\s*(.*)$/gm, '<div class="font-bold text-[14px] mt-2 mb-1">$1</div>')
    .replace(/^#\s*(.*)$/gm, '<div class="font-bold text-[15px] mt-2 mb-1">$1</div>');

  // Inline formatting (bold, italic, code)
  processed = processed
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono text-[10px]">$1</code>');

  // Numbered lists: lines starting with '1. ' or '1) '
  processed = processed.replace(/^\s*(\d+)[\.\)]\s+(.*)$/gm, '<li class="ol-item ml-1">$2</li>');
  processed = processed.replace(/((?:<li class="ol-item ml-1">.*?<\/li>\s*)+)/gs, function(match) {
    const items = match.replace(/<\/li>\s+<li/g, '</li><li').trim();
    return `<ol class="space-y-1.5 my-2 list-decimal pl-5">${items}</ol>`;
  });

  // Bullet lists: lines starting with '- ', '* ', or '• '
  processed = processed.replace(/^\s*[-*•]\s+(.*)$/gm, '<li class="ul-item ml-1">$1</li>');
  processed = processed.replace(/((?:<li class="ul-item ml-1">.*?<\/li>\s*)+)/gs, function(match) {
    const items = match.replace(/<\/li>\s+<li/g, '</li><li').trim();
    return `<ul class="space-y-1 my-2 list-disc pl-5">${items}</ul>`;
  });

  // Line breaks and paragraphs
  processed = processed.replace(/<\/li>\s*<li/g, '</li><li');
  processed = processed.replace(/\n{2,}/g, '<br/><br/>');
  processed = processed.replace(/\n/g, '<br/>');
  processed = processed
    .replace(/(?:<br\/>)+(<\/?(?:ol|ul|li|div|table|tbody|tr|td))/gi, '$1')
    .replace(/(<\/(?:ol|ul|li|div|table|tbody|tr|td)>)(?:<br\/>)+/gi, '$1');

  return processed.trim();
}

// ── Portfolio Doctor & AI Advisory ──
async function loadPortfolioAdvisory(silent = false) {
  if (!getAuthToken()) {
    return;
  }
  const btn = document.getElementById('adv-diag-btn');
  if (btn && !silent) btn.innerHTML = '<i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i><span>Diagnosing...</span>';
  try {
    const res = await fetch('/api/v1/portfolio/advisory', { headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      if (typeof resetPortfolioUI === 'function') resetPortfolioUI(true);
      if (!silent) openLoginModal();
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    globalAdvisoryData = data;
    renderAdvisoryData(data);
  } catch (err) {
    console.error('Advisory load error:', err);
  } finally {
    if (btn && !silent) btn.innerHTML = '<i data-lucide="activity" class="w-3 h-3 text-emerald-500"></i><span>Run Diagnosis</span>';
    refreshLucideIcons();
  }
}

function renderAdvisoryData(data) {
  if (!data) return;
  const score = data.health_score || 50;
  const scoreEl = document.getElementById('adv-health-score');
  if (scoreEl) scoreEl.textContent = score;

  const gaugePath = document.getElementById('adv-gauge-path');
  if (gaugePath) {
    const pct = Math.min(100, Math.max(0, score));
    gaugePath.setAttribute('stroke-dasharray', `${pct}, 100`);
    if (score >= 70) gaugePath.setAttribute('class', 'text-emerald-500 transition-all duration-700 ease-out');
    else if (score >= 56) gaugePath.setAttribute('class', 'text-blue-500 transition-all duration-700 ease-out');
    else if (score >= 42) gaugePath.setAttribute('class', 'text-amber-500 transition-all duration-700 ease-out');
    else gaugePath.setAttribute('class', 'text-rose-500 transition-all duration-700 ease-out');
  }

  const verdictEl = document.getElementById('adv-health-verdict-badge');
  if (verdictEl && data.health_verdict) {
    verdictEl.textContent = data.verdict_badge || `● ${data.health_verdict}`;
    if (score >= 70) {
      verdictEl.className = "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/80 text-emerald-800 dark:text-emerald-300";
    } else if (score >= 56) {
      verdictEl.className = "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-950/80 text-blue-800 dark:text-blue-300";
    } else if (score >= 42) {
      verdictEl.className = "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300";
    } else {
      verdictEl.className = "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-100 dark:bg-rose-950/80 text-rose-800 dark:text-rose-300";
    }
  }

  const regimeEl = document.getElementById('adv-regime-text');
  if (regimeEl && data.market_sentiment) {
    regimeEl.textContent = `Regime: ${data.market_sentiment.regime || 'Bullish Base'}`;
  }

  const summaryEl = document.getElementById('adv-summary-text');
  if (summaryEl && data.summary) {
    summaryEl.textContent = data.summary;
    summaryEl.setAttribute('title', data.summary);
  }

  // Render 3 Horizontal Strategic Priority Cards
  const checklistEl = document.getElementById('adv-checklist');
  if (checklistEl && data.action_checklist?.length) {
    checklistEl.innerHTML = data.action_checklist.slice(0, 3).map(item => {
      if (typeof item === 'object') {
        const iconMap = { opportunity: 'trending-up', protection: 'shield', profit: 'pie-chart' };
        const iconName = iconMap[item.type] || 'check-circle-2';
        const cleanDesc = formatAIMarkdown(item.desc || '');
        return `
          <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 space-y-1">
            <div class="flex items-center justify-between gap-1">
              <span class="text-xs font-bold text-slate-800 dark:text-white flex items-center gap-1.5 truncate">
                <i data-lucide="${iconName}" class="w-3.5 h-3.5 text-emerald-500 shrink-0"></i>
                <span class="truncate">${item.title || 'Insight'}</span>
              </span>
              ${item.badge ? `<span class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 shrink-0">${item.badge}</span>` : ''}
            </div>
            <div class="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
              ${cleanDesc}
            </div>
          </div>
        `;
      } else {
        const cleanText = formatAIMarkdown(item);
        return `
          <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-800 text-[11px] text-slate-600 dark:text-slate-400 leading-snug">
            ${cleanText}
          </div>
        `;
      }
    }).join('');
  }
  refreshLucideIcons();
}

// ── Technical Strategy Scorecard Loader ──
async function loadScorecard() {
  try {
    const res = await fetch('/api/v1/portfolio/scorecard', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    const contentEl = document.getElementById('scorecard-content');
    const badgeEl = document.getElementById('scorecard-badge');
    if (!contentEl) return;

    const closed = data.closed_diagnoses ?? data.closed_picks ?? 0;
    const minReq = data.min_required || 30;
    const total = data.total_diagnoses ?? data.total_picks ?? closed;

    if (data.status === 'not_enough_data' || closed < minReq) {
      const pct = Math.min(100, Math.round((closed / minReq) * 100));
      if (badgeEl) {
        badgeEl.textContent = `${closed}/${minReq} Closed`;
        badgeEl.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500';
      }
      contentEl.innerHTML = `
        <div class="p-3 rounded-lg bg-slate-50/70 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800 text-center space-y-1.5">
          <div class="flex items-center justify-between text-[11px]">
            <span class="text-slate-500 dark:text-slate-400">Sample Progress</span>
            <span class="font-mono font-bold text-slate-700 dark:text-slate-300">${closed} / ${minReq} Diagnoses</span>
          </div>
          <div class="w-full bg-slate-200 dark:bg-slate-700 h-1.5 rounded-full overflow-hidden">
            <div class="bg-emerald-500 h-full transition-all duration-500" style="width: ${pct}%"></div>
          </div>
          <p class="text-[10px] text-slate-400 leading-tight">
            Collecting data (${closed}/${minReq} closed diagnoses). Hit rate activates once 30+ diagnoses close.
          </p>
          <p class="text-[9px] text-slate-400 italic">Mechanical technical levels, not a forecast or investment advice.</p>
        </div>
      `;
    } else {
      if (badgeEl) {
        badgeEl.textContent = 'Active Track Record';
        badgeEl.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300';
      }
      contentEl.innerHTML = `
        <div class="grid grid-cols-2 gap-2 pt-1">
          <div class="p-2.5 rounded-lg bg-slate-50/70 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800">
            <p class="text-[10px] text-slate-400 uppercase font-semibold">Hit Rate</p>
            <p class="text-sm font-bold font-mono text-emerald-600 dark:text-emerald-400 mt-0.5">${data.hit_rate_pct}%</p>
            <p class="text-[9px] text-slate-400">${data.target_hits || 0} won / ${data.stop_hits || 0} stop</p>
          </div>
          <div class="p-2.5 rounded-lg bg-slate-50/70 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800">
            <p class="text-[10px] text-slate-400 uppercase font-semibold">Total Sample</p>
            <p class="text-sm font-bold font-mono text-slate-900 dark:text-white mt-0.5">${closed}</p>
            <p class="text-[9px] text-slate-400">${total} evaluated</p>
          </div>
        </div>
        <p class="text-[9px] text-slate-400 text-center italic mt-2">Mechanical technical levels, not a forecast or investment advice.</p>
      `;
    }
    refreshLucideIcons();
  } catch (e) {
    console.debug('Scorecard fetch notice:', e);
  }
}

// ── AI Portfolio Copilot Floating Dock & Interactive Chat ──
function updateWelcomeBoxVisibility() {
  const welcomeBox = document.getElementById('ai-welcome-box');
  if (!welcomeBox) return;
  const input = document.getElementById('ai-modal-input');
  const hasText = input && input.value.trim().length > 0;
  if (hasText) {
    welcomeBox.classList.add('hidden');
  } else if (!aiChatHistory || aiChatHistory.length === 0) {
    welcomeBox.classList.remove('hidden');
  }
}

function setupAICopilotInputListener() {
  const input = document.getElementById('ai-modal-input');
  if (!input || input.dataset.welcomeListenerBound) return;
  input.dataset.welcomeListenerBound = 'true';
  input.addEventListener('input', updateWelcomeBoxVisibility);
  input.addEventListener('keyup', updateWelcomeBoxVisibility);
}

function initAICopilotGreeting() {
  const chatContainer = document.getElementById('ai-modal-chat-messages');
  if (!chatContainer) return;
  chatContainer.innerHTML = `
    <div id="ai-welcome-box" class="bg-[#F5EFEB] dark:bg-[#1B2433] border border-[#E8DFD5] dark:border-slate-700/60 rounded-[22px] p-4 sm:p-5 text-[#2D2A26] dark:text-slate-200 text-xs sm:text-[13px] leading-relaxed space-y-2.5 shadow-2xs">
      <p class="font-bold text-[#1C1A17] dark:text-white flex items-center gap-2">
        <span>Welcome to IPO Pulse AI Copilot</span>
      </p>
      <p>
        I analyze your live equity holdings, cost bases, profit harvesting levels, and trailing stop-loss guards in real-time. You can ask me specific questions regarding any stock or IPO.
      </p>
      <p class="text-[11px] text-[#7C7164] dark:text-slate-400">
        Click a suggested topic below or type anything in the prompt box to begin.
      </p>
      <p class="text-[10px] text-[#8E8477] dark:text-slate-400 italic pt-0.5 border-t border-[#E8DFD5]/60 dark:border-slate-700/40">
        IPO PULSE Copilot is an AI and can make mistakes.
      </p>
    </div>

    <div class="flex flex-wrap gap-2 pt-1" id="ai-quick-suggestions-box">
      <button type="button" onclick="askAICopilotPrompt('How to make my portfolio green?')" class="rounded-full border border-[#DDD4C7] dark:border-slate-700 bg-[#FFFDFB] dark:bg-[#121826] hover:bg-[#F2ECE3] dark:hover:bg-slate-800/80 px-3.5 py-1.5 text-xs font-semibold text-[#4A443B] dark:text-slate-300 transition shadow-2xs cursor-pointer active:scale-95">
        🌿 Turn Portfolio Green
      </button>
      <button type="button" onclick="askAICopilotPrompt('Show stop loss levels for all holdings')" class="rounded-full border border-[#DDD4C7] dark:border-slate-700 bg-[#FFFDFB] dark:bg-[#121826] hover:bg-[#F2ECE3] dark:hover:bg-slate-800/80 px-3.5 py-1.5 text-xs font-semibold text-[#4A443B] dark:text-slate-300 transition shadow-2xs cursor-pointer active:scale-95">
        🛡️ Stop-Loss Check
      </button>
      <button type="button" onclick="askAICopilotPrompt('What is the best stock to buy on dip?')" class="rounded-full border border-[#DDD4C7] dark:border-slate-700 bg-[#FFFDFB] dark:bg-[#121826] hover:bg-[#F2ECE3] dark:hover:bg-slate-800/80 px-3.5 py-1.5 text-xs font-semibold text-[#4A443B] dark:text-slate-300 transition shadow-2xs cursor-pointer active:scale-95">
        🎯 Top Dip Pick
      </button>
      <button type="button" onclick="askAICopilotPrompt('What is my overall profit and loss till now?')" class="rounded-full border border-[#DDD4C7] dark:border-slate-700 bg-[#FFFDFB] dark:bg-[#121826] hover:bg-[#F2ECE3] dark:hover:bg-slate-800/80 px-3.5 py-1.5 text-xs font-semibold text-[#4A443B] dark:text-slate-300 transition shadow-2xs cursor-pointer active:scale-95">
        💼 Overall P&L Till Now
      </button>
    </div>
  `;
  refreshLucideIcons();
  setupAICopilotInputListener();
}

function openAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (!modal) return;
  modal.classList.remove('ai-modal-closed');
  modal.classList.add('ai-modal-open');

  const chatContainer = document.getElementById('ai-modal-chat-messages');
  if (chatContainer && chatContainer.children.length === 0) {
    initAICopilotGreeting();
  }
  setupAICopilotInputListener();

  refreshLucideIcons();
  setTimeout(() => {
    const input = document.getElementById('ai-modal-input');
    if (input) input.focus();
  }, 250);
}

function closeAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (!modal) return;
  modal.classList.remove('ai-modal-open');
  modal.classList.add('ai-modal-closed');
}

function resetAICopilotChat() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  aiChatHistory = [];
  initAICopilotGreeting();
  const input = document.getElementById('ai-modal-input');
  if (input) {
    input.value = '';
    updateWelcomeBoxVisibility();
    input.focus();
  }
}

function toggleAICopilotVoice() {
  aiVoiceEnabled = !aiVoiceEnabled;
  const icon = document.getElementById('ai-voice-icon');
  const btn = document.getElementById('ai-voice-btn');
  if (aiVoiceEnabled) {
    if (icon) icon.setAttribute('data-lucide', 'volume-2');
    if (btn) btn.className = "p-1.5 rounded-lg text-amber-700 dark:text-amber-400 bg-[#F2ECE3] dark:bg-amber-950/60 transition cursor-pointer";
    speakAIText("Voice read-aloud enabled");
  } else {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (icon) icon.setAttribute('data-lucide', 'volume-x');
    if (btn) btn.className = "p-1.5 rounded-lg text-[#7C7164] dark:text-slate-400 hover:text-[#2D2A26] dark:hover:text-white hover:bg-[#F0EAE1] dark:hover:bg-slate-800/80 transition cursor-pointer";
  }
  refreshLucideIcons();
}

function speakAIText(text) {
  if (!aiVoiceEnabled || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const plainText = text.replace(/<[^>]*>?/gm, '').replace(/[*#`_]/g, '');
  const utterance = new SpeechSynthesisUtterance(plainText);
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  window.speechSynthesis.speak(utterance);
}

function toggleQuickPromptSuggestions() {
  const input = document.getElementById('ai-modal-input');
  if (input) {
    input.focus();
    if (!input.value) {
      input.value = 'How to make my portfolio green?';
    }
    updateWelcomeBoxVisibility();
  }
}

function toggleAICopilotModal() {
  const modal = document.getElementById('ai-copilot-modal');
  if (modal && modal.classList.contains('ai-modal-open')) {
    closeAICopilotModal();
  } else {
    openAICopilotModal();
  }
}

function askAICopilotPrompt(promptText) {
  const input = document.getElementById('ai-modal-input');
  if (input) {
    input.value = promptText;
    updateWelcomeBoxVisibility();
  }
  submitAICopilotChat();
}

async function submitAICopilotChat(e) {
  if (e) e.preventDefault();
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const input = document.getElementById('ai-modal-input');
  const sendBtn = document.getElementById('ai-modal-send-btn');
  const chatContainer = document.getElementById('ai-modal-chat-messages');
  if (!input || !chatContainer) return;

  const query = input.value.trim();
  if (!query) return;

  // Immediately remove welcome box and quick suggestions on first question
  const welcomeBox = document.getElementById('ai-welcome-box');
  if (welcomeBox) welcomeBox.remove();
  const suggestionsBox = document.getElementById('ai-quick-suggestions-box');
  if (suggestionsBox) suggestionsBox.remove();

  // 1. Append User Bubble (Warm dark tone)
  const userBubble = document.createElement('div');
  userBubble.className = 'flex items-start justify-end';
  userBubble.innerHTML = `
    <div class="bg-[#24211D] text-[#FAF8F5] dark:bg-indigo-600 dark:text-white rounded-[20px] rounded-br-xs px-4 py-2.5 text-xs sm:text-[13px] max-w-[85%] shadow-xs leading-relaxed">
      ${query.replace(/</g, '&lt;').replace(/>/g, '&gt;')}
    </div>
  `;
  chatContainer.appendChild(userBubble);
  input.value = '';

  // 2. Append Typing Indicator
  const typingIndicator = document.createElement('div');
  typingIndicator.id = 'ai-typing-indicator';
  typingIndicator.className = 'flex items-start';
  typingIndicator.innerHTML = `
    <div class="bg-[#F5EFEB] dark:bg-[#1A2234] border border-[#E8DFD5] dark:border-slate-700/60 rounded-[20px] px-4 py-3 text-xs text-[#7C7164] dark:text-slate-400 max-w-[90%] flex items-center gap-2 shadow-2xs">
      <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-amber-600 shrink-0"></i>
      <span>Analyzing portfolio momentum &amp; levels...</span>
    </div>
  `;
  chatContainer.appendChild(typingIndicator);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  refreshLucideIcons();

  const recentHistory = aiChatHistory.slice(-6);
  aiChatHistory.push({ role: 'user', content: query });

  try {
    const res = await fetch('/api/v1/portfolio/advisory/ask', {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ query: query, history: recentHistory })
    });
    if (res.status === 401) {
      openLoginModal();
      throw new Error('Authentication required. Please sign in to ask AI questions.');
    }
    if (res.status === 429) {
      throw new Error('Rate limit reached (10 questions/min). Please wait a moment.');
    }
    const rawText = await res.text();
    if (!res.ok) {
      let errDetail = `Failed to get answer (HTTP ${res.status})`;
      if (rawText) {
        try {
          const errData = JSON.parse(rawText);
          errDetail = errData.detail || errData.message || errDetail;
        } catch (_) {
          if (/^\s*<!doctype|^\s*<html/i.test(rawText)) {
            errDetail = `Advisor service temporarily unavailable or timed out (HTTP ${res.status}). Please try again.`;
          } else {
            errDetail = rawText.trim().slice(0, 240) || errDetail;
          }
        }
      }
      throw new Error(errDetail);
    }
    const data = JSON.parse(rawText);

    aiChatHistory.push({ role: 'assistant', content: data.answer });
    if (aiChatHistory.length > 20) aiChatHistory = aiChatHistory.slice(-20);

    const indicator = document.getElementById('ai-typing-indicator');
    if (indicator) indicator.remove();

    const isFallback = (data.source === 'fallback');
    const fallbackBadge = isFallback 
      ? `<div class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60 mb-1 select-none">
           <i data-lucide="shield-alert" class="w-3 h-3 text-amber-600 dark:text-amber-400"></i>
           <span>Basic mode</span>
         </div>` 
      : '';

    // 3. Append AI Response Bubble (Warm Tone)
    const aiBubble = document.createElement('div');
    aiBubble.className = 'flex items-start';
    aiBubble.innerHTML = `
      <div class="bg-[#F5EFEB] dark:bg-[#1A2234] border border-[#E8DFD5] dark:border-slate-700/60 rounded-[22px] px-4 py-3.5 text-xs sm:text-[13px] text-[#2D2A26] dark:text-slate-200 max-w-[92%] leading-relaxed shadow-2xs space-y-1.5">
        ${fallbackBadge}
        <div>${formatAIMarkdown(data.answer)}</div>
      </div>
    `;
    chatContainer.appendChild(aiBubble);
    speakAIText(data.answer);
  } catch (err) {
    const indicator = document.getElementById('ai-typing-indicator');
    if (indicator) indicator.remove();

    const errBubble = document.createElement('div');
    errBubble.className = 'flex items-start';
    errBubble.innerHTML = `
      <div class="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 rounded-[20px] px-4 py-3 text-xs text-rose-700 dark:text-rose-300 max-w-[90%] shadow-2xs">
        Failed to query AI advisor: ${err.message}
      </div>
    `;
    chatContainer.appendChild(errBubble);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    chatContainer.scrollTop = chatContainer.scrollHeight;
    refreshLucideIcons();
  }
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupAICopilotInputListener);
  } else {
    setupAICopilotInputListener();
  }
}

