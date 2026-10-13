// ==================== PORTFOLIO & HOLDINGS MANAGEMENT ====================

function resetPortfolioUI(isSignedOut = true) {
  currentPortfolioHoldings = [];
  previousHoldingsPrices = {};
  globalAdvisoryData = null;

  // Summary Strip
  const investedEl = document.getElementById('pf-invested');
  if (investedEl) investedEl.textContent = '—';

  const valueEl = document.getElementById('pf-value');
  if (valueEl) valueEl.textContent = '—';

  const dayChip = document.getElementById('pf-day-chip');
  if (dayChip) {
    dayChip.innerHTML = 'Today: —';
    dayChip.className = 'inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-md mt-1 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 tabular-nums';
  }

  const pnlEl = document.getElementById('pf-pnl');
  if (pnlEl) {
    pnlEl.textContent = '—';
    pnlEl.className = 'text-xl sm:text-2xl font-bold font-mono text-slate-900 dark:text-white tabular-nums';
  }

  const pnlChip = document.getElementById('pf-pnl-chip');
  if (pnlChip) {
    pnlChip.textContent = '—';
    pnlChip.className = 'inline-flex items-center gap-0.5 text-[11px] font-bold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 tabular-nums';
  }

  const countEl = document.getElementById('pf-count');
  if (countEl) countEl.textContent = '—';

  const gainersLosersEl = document.getElementById('pf-gainers-losers');
  if (gainersLosersEl) gainersLosersEl.innerHTML = '<span>●</span> —';

  const unpricedEl = document.getElementById('pf-unpriced-warning');
  if (unpricedEl) {
    unpricedEl.textContent = '';
    unpricedEl.classList.add('hidden');
  }

  // Holdings Table & Cards
  const loadingEl = document.getElementById('pf-loading');
  if (loadingEl) loadingEl.classList.add('hidden');

  const containerEl = document.getElementById('pf-holdings-container');
  if (containerEl) containerEl.classList.add('hidden');

  const tbody = document.getElementById('pf-tbody');
  if (tbody) tbody.innerHTML = '';

  const cardsWrap = document.getElementById('pf-cards-wrap');
  if (cardsWrap) cardsWrap.innerHTML = '';

  const emptyEl = document.getElementById('pf-empty');
  if (emptyEl) {
    emptyEl.classList.remove('hidden');
    if (isSignedOut) {
      emptyEl.innerHTML = `
        <div class="h-12 w-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
          <i data-lucide="lock" class="w-6 h-6"></i>
        </div>
        <div>
          <h4 class="font-bold text-slate-800 dark:text-white text-sm">Sign in to view your portfolio</h4>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 max-w-sm mx-auto">Your holdings, valuations, and real-time P&amp;L are protected. Please sign in or create an account to access your portfolio.</p>
        </div>
        <div class="flex items-center justify-center pt-2 gap-2.5">
          <button onclick="openLoginModal('signin')" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition shadow-sm cursor-pointer flex items-center gap-1.5">
            <i data-lucide="log-in" class="w-3.5 h-3.5"></i>
            <span>Sign In</span>
          </button>
          <button onclick="openLoginModal('signup')" class="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-bold transition shadow-sm cursor-pointer flex items-center gap-1.5 border border-slate-300/70 dark:border-slate-700">
            <i data-lucide="user-plus" class="w-3.5 h-3.5"></i>
            <span>Create Account</span>
          </button>
        </div>
      `;
    } else {
      emptyEl.innerHTML = `
        <div class="h-12 w-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
          <i data-lucide="briefcase" class="w-6 h-6"></i>
        </div>
        <div>
          <h4 class="font-bold text-slate-800 dark:text-white text-sm">No holdings yet</h4>
          <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 max-w-sm mx-auto">Import your broker Excel/CSV statement or add your first stock to begin tracking.</p>
        </div>
        <div class="flex items-center justify-center gap-2 pt-2">
          <label class="px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition shadow-sm cursor-pointer">
            Import Statement (.xlsx / .csv)
            <input type="file" accept=".csv, .xlsx, .xls" class="hidden" onchange="importCSV(event)">
          </label>
          <button onclick="openAddHoldingModal()" class="px-3.5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 text-xs font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition">
            + Add Manually
          </button>
        </div>
      `;
    }
  }

  // Allocation Donut
  const donutSvg = document.getElementById('donut-chart-svg') || document.getElementById('donut-svg');
  if (donutSvg) donutSvg.innerHTML = '<circle cx="21" cy="21" r="15.915" fill="none" stroke="#E2E8F0" stroke-width="6"/>';

  const donutVal = document.getElementById('donut-total-val') || document.getElementById('donut-center-val');
  if (donutVal) donutVal.textContent = '—';

  const donutLegend = document.getElementById('donut-legend');
  if (donutLegend) donutLegend.innerHTML = `<div class="text-xs text-slate-400 text-center py-2">${isSignedOut ? 'Sign in to view allocation' : 'No holdings allocated'}</div>`;

  // AI Strategic Priorities Checklist
  const checklistEl = document.getElementById('adv-checklist');
  if (checklistEl) {
    checklistEl.innerHTML = `<div class="text-xs text-slate-400 text-center py-2">${isSignedOut ? 'Sign in to view strategic priorities' : 'No active alerts'}</div>`;
  }

  // AI Portfolio Doctor
  const advScore = document.getElementById('adv-health-score');
  if (advScore) advScore.textContent = '—';

  const gauge = document.getElementById('adv-gauge-path');
  if (gauge) gauge.setAttribute('stroke-dasharray', '0, 100');

  const verdict = document.getElementById('adv-health-verdict-badge');
  if (verdict) {
    verdict.textContent = isSignedOut ? '● Signed Out' : '● No Data';
    verdict.className = 'inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400';
  }

  const summaryText = document.getElementById('adv-summary-text');
  if (summaryText) summaryText.textContent = isSignedOut ? 'Sign in to run real-time technical diagnosis and portfolio health checks.' : 'Add holdings to analyze technical indicators and momentum.';

  const regimeText = document.getElementById('adv-regime-text');
  if (regimeText) regimeText.textContent = 'Regime: —';

  // Reset Copilot chat state & close modal if open
  if (typeof closeAICopilotModal === 'function') closeAICopilotModal();
  const chatMessages = document.getElementById('ai-modal-chat-messages');
  if (chatMessages) chatMessages.innerHTML = '';
  aiChatHistory = [];

  // Reset & dispose charts
  if (typeof activeHoldingCharts !== 'undefined') {
    Object.keys(activeHoldingCharts).forEach(sym => {
      if (typeof disposeHoldingChart === 'function') disposeHoldingChart(sym);
    });
  }
  if (portfolioSnapshotsChart) {
    portfolioSnapshotsChart.destroy();
    portfolioSnapshotsChart = null;
  }
  if (pnlByStockChart) {
    pnlByStockChart.destroy();
    pnlByStockChart = null;
  }
  const pnlEmpty = document.getElementById('pnl-stocks-empty');
  if (pnlEmpty) pnlEmpty.classList.remove('hidden');
  const pnlBox = document.getElementById('pnl-stocks-chart-container');
  if (pnlBox) pnlBox.classList.add('hidden');
  const snapCollect = document.getElementById('snapshots-collecting-state');
  if (snapCollect) snapCollect.classList.remove('hidden');
  const snapBox = document.getElementById('snapshots-chart-container');
  if (snapBox) snapBox.classList.add('hidden');

  refreshLucideIcons();
}

async function loadPortfolio(silent = false) {
  if (!getAuthToken()) {
    resetPortfolioUI(true);
    if (!silent) openLoginModal();
    return;
  }

  if (!silent) {
    document.getElementById('pf-loading').classList.remove('hidden');
    document.getElementById('pf-empty').classList.add('hidden');
    document.getElementById('pf-holdings-container').classList.add('hidden');
  }

  try {
    const res = await fetch(`${API}/summary`, { headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      resetPortfolioUI(true);
      if (!silent) openLoginModal();
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderPortfolioSummary(data);
    currentPortfolioHoldings = data.holdings || [];
    renderHoldings(currentPortfolioHoldings);
    if (typeof renderAllocationDonut === 'function') renderAllocationDonut(currentPortfolioHoldings, data.current_value);
    if (typeof renderPortfolioSnapshotsChart === 'function') renderPortfolioSnapshotsChart();
    if (typeof renderPnlByStockChart === 'function') renderPnlByStockChart(currentPortfolioHoldings);
    if (typeof loadPortfolioAdvisory === 'function') loadPortfolioAdvisory(silent);
    if (typeof loadScorecard === 'function') loadScorecard();
    loadCombinedNetWorth();
  } catch (err) {
    console.error('Portfolio load failed:', err);
    if (!silent) {
      document.getElementById('pf-loading').textContent = 'Failed to load portfolio.';
    }
  } finally {
    refreshLucideIcons();
  }
}

function renderPortfolioSummary(data) {
  document.getElementById('pf-loading').classList.add('hidden');
  document.getElementById('pf-invested').textContent = fmtINR(data.total_invested);
  document.getElementById('pf-value').textContent = fmtINR(data.current_value);

  // Today's Change Chip under Current Value
  const dayVal = data.day_change || 0;
  const dayPct = data.day_change_pct || 0;
  const dayIsPos = dayVal >= 0;
  const dayChip = document.getElementById('pf-day-chip');
  const dayArrow = dayIsPos ? '▲' : '▼';
  const dayBg = dayIsPos 
    ? 'bg-[#DCFCE7] dark:bg-[#064E3B] text-[#16A34A] dark:text-[#34D399]' 
    : 'bg-[#FEE2E2] dark:bg-[#7F1D1D] text-[#DC2626] dark:text-[#F87171]';
  dayChip.className = `inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${dayBg} tabular-nums mt-1 whitespace-nowrap`;
  dayChip.innerHTML = `Today: ${dayArrow} ${fmtINR(dayVal)} (${fmtPct(dayPct)})`;

  // Unrealized P&L
  const pnl = data.total_unrealized_pnl || 0;
  const pnlPct = data.total_pnl_pct || 0;
  const pnlEl = document.getElementById('pf-pnl');
  pnlEl.textContent = fmtINR(pnl);
  pnlEl.className = `text-xl sm:text-2xl font-bold font-mono tabular-nums whitespace-nowrap ${pnlColorClass(pnl)}`;

  const pnlChip = document.getElementById('pf-pnl-chip');
  const pnlIsPos = pnl >= 0;
  const pnlBg = pnlIsPos 
    ? 'bg-[#DCFCE7] dark:bg-[#064E3B] text-[#16A34A] dark:text-[#34D399]' 
    : 'bg-[#FEE2E2] dark:bg-[#7F1D1D] text-[#DC2626] dark:text-[#F87171]';
  pnlChip.className = `inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${pnlBg} tabular-nums whitespace-nowrap`;
  pnlChip.innerHTML = `${pnlIsPos ? '▲' : '▼'} ${fmtPct(pnlPct)}`;

  // Positions count & Gainers/Losers dots
  document.getElementById('pf-count').textContent = data.holdings_count || '0';
  document.getElementById('pf-gainers-losers').innerHTML = 
    `<span class="inline-block w-2 h-2 rounded-full bg-emerald-500"></span> ${data.gainers || 0} up · <span class="inline-block w-2 h-2 rounded-full bg-rose-500"></span> ${data.losers || 0} down`;

  const unpricedEl = document.getElementById('pf-unpriced-warning');
  if (unpricedEl) {
    if (data.unpriced_count && data.unpriced_count > 0) {
      unpricedEl.textContent = `${data.unpriced_count} holding(s) unpriced, excluded from totals`;
      unpricedEl.classList.remove('hidden');
    } else {
      unpricedEl.classList.add('hidden');
    }
  }
}

function sortHoldings(col) {
  if (currentSortCol === col) {
    currentSortAsc = !currentSortAsc;
  } else {
    currentSortCol = col;
  }
  renderHoldings(currentPortfolioHoldings);
}

function filterHoldingsTable() {
  const q = (document.getElementById('holdings-search-input')?.value || '').toLowerCase().trim();
  const filtered = currentPortfolioHoldings.filter(h => 
    h.symbol.toLowerCase().includes(q) || h.company_name.toLowerCase().includes(q)
  );
  renderHoldings(filtered, true, true);
}

function updateHoldingsFooter(list) {
  let sumQty = 0;
  let sumInvested = 0;
  let sumCurrentVal = 0;
  let sumDayChgAmt = 0;

  list.forEach(h => {
    const qty = Number(h.quantity) || 0;
    const invested = Number(h.invested_value != null ? h.invested_value : (h.avg_buy_price * qty)) || 0;
    const currVal = Number(h.current_value != null ? h.current_value : (h.live_price ? h.live_price * qty : invested)) || 0;
    const dayPct = Number(h.day_change_pct) || 0;
    const prevVal = currVal / (1 + dayPct / 100);
    const dayAmt = currVal - prevVal;

    sumQty += qty;
    sumInvested += invested;
    sumCurrentVal += currVal;
    sumDayChgAmt += dayAmt;
  });

  const totalPnl = sumCurrentVal - sumInvested;
  const totalPnlPct = sumInvested > 0 ? (totalPnl / sumInvested) * 100 : 0;
  const totalDayPct = (sumCurrentVal - sumDayChgAmt) > 0 ? (sumDayChgAmt / (sumCurrentVal - sumDayChgAmt)) * 100 : 0;

  const tfootQty = document.getElementById('tfoot-qty');
  const tfootInvested = document.getElementById('tfoot-invested');
  const tfootCurrVal = document.getElementById('tfoot-curr-val');
  const tfootPnlVal = document.getElementById('tfoot-pnl-val');
  const tfootPnlChip = document.getElementById('tfoot-pnl-chip');
  const tfootDayChg = document.getElementById('tfoot-day-chg');

  if (tfootQty) tfootQty.textContent = '—';
  if (tfootInvested) tfootInvested.textContent = fmtINR(sumInvested);
  if (tfootCurrVal) tfootCurrVal.textContent = fmtINR(sumCurrentVal);
  if (tfootPnlVal) {
    tfootPnlVal.textContent = fmtINR(totalPnl);
    tfootPnlVal.className = `font-mono font-extrabold tabular-nums ${pnlColorClass(totalPnl)}`;
  }
  if (tfootPnlChip) {
    tfootPnlChip.innerHTML = pnlChipHTML(totalPnlPct);
  }
  if (tfootDayChg) {
    tfootDayChg.innerHTML = `<div>${fmtINR(sumDayChgAmt)}</div><div class="mt-0.5">${pnlChipHTML(totalDayPct, true)}</div>`;
  }
}

function renderHoldings(holdings, skipSorting = false, forceFullBuild = false) {
  const tbody = document.getElementById('pf-tbody');
  const cardsWrap = document.getElementById('pf-cards-wrap');
  const container = document.getElementById('pf-holdings-container');
  if (!tbody) return;

  if (!holdings || holdings.length === 0) {
    document.getElementById('pf-empty').classList.remove('hidden');
    if (container) container.classList.add('hidden');
    tbody.innerHTML = '';
    if (cardsWrap) cardsWrap.innerHTML = '';
    return;
  }

  document.getElementById('pf-empty').classList.add('hidden');
  if (container) container.classList.remove('hidden');

  let list = [...holdings];
  if (!skipSorting && currentSortCol) {
    list.sort((a, b) => {
      let valA = a[currentSortCol];
      let valB = b[currentSortCol];
      if (typeof valA === 'string') valA = valA.toLowerCase();
      if (typeof valB === 'string') valB = valB.toLowerCase();
      if (valA < valB) return currentSortAsc ? -1 : 1;
      if (valA > valB) return currentSortAsc ? 1 : -1;
      return 0;
    });
  }

  // Check if we can perform an IN-PLACE update (same symbols and count)
  const existingRows = Array.from(tbody.querySelectorAll('tr[data-holding-symbol]'));
  const canUpdateInPlace = !forceFullBuild && 
    existingRows.length === list.length && 
    list.every((h, i) => existingRows[i]?.dataset.holdingSymbol === h.symbol);

  if (canUpdateInPlace) {
    list.forEach(h => {
      const pnl = h.unrealized_pnl || 0;
      const pnlPct = h.pnl_pct || 0;
      const dayChg = h.day_change_pct || 0;
      const ltp = h.live_price || h.avg_buy_price;
      const prevPrice = previousHoldingsPrices[h.symbol];

      let flashClass = '';
      if (prevPrice !== undefined && prevPrice !== null && prevPrice !== ltp) {
        flashClass = ltp > prevPrice ? 'flash-green' : 'flash-red';
      }
      previousHoldingsPrices[h.symbol] = ltp;

      const row = document.getElementById('pf-row-' + h.symbol);
      if (row) {
        const qtyEl = row.querySelector('.cell-qty');
        if (qtyEl) qtyEl.textContent = h.quantity;
        const avgEl = row.querySelector('.cell-avg');
        if (avgEl) avgEl.textContent = fmtINR(h.avg_buy_price);
        
        const ltpEl = row.querySelector('.cell-ltp');
        if (ltpEl) {
          ltpEl.textContent = fmtINR(ltp);
          if (flashClass) {
            ltpEl.classList.remove('flash-green', 'flash-red');
            void ltpEl.offsetWidth;
            ltpEl.classList.add(flashClass);
            setTimeout(() => ltpEl.classList.remove(flashClass), 1200);
          }
        }

        const curValEl = row.querySelector('.cell-curval');
        if (curValEl) curValEl.textContent = fmtINR(h.current_value);

        const pnlValEl = row.querySelector('.cell-pnl-val');
        if (pnlValEl) {
          pnlValEl.textContent = fmtINR(pnl);
          pnlValEl.className = 'cell-pnl-val font-mono font-bold tabular-nums ' + pnlColorClass(pnl);
        }

        const pnlChipEl = row.querySelector('.cell-pnl-chip');
        if (pnlChipEl) pnlChipEl.innerHTML = pnlChipHTML(pnlPct);

        const dayChgEl = row.querySelector('.cell-daychg');
        if (dayChgEl) dayChgEl.innerHTML = pnlChipHTML(dayChg, true);

        const cellTrendEl = row.querySelector('.cell-trend');
        if (cellTrendEl && typeof renderSparkline === 'function') {
          cellTrendEl.innerHTML = renderSparkline(h.trend_closes);
        }
      }

      // In-place update for Mobile Card
      const card = document.getElementById('pf-card-' + h.symbol);
      if (card) {
        const mLtp = card.querySelector('.mcell-ltp');
        if (mLtp) {
          mLtp.textContent = fmtINR(ltp);
          if (flashClass) {
            mLtp.classList.remove('flash-green', 'flash-red');
            void mLtp.offsetWidth;
            mLtp.classList.add(flashClass);
            setTimeout(() => mLtp.classList.remove(flashClass), 1200);
          }
        }
        const mDay = card.querySelector('.mcell-daychg');
        if (mDay) mDay.innerHTML = pnlChipHTML(dayChg, true);
        const mPnl = card.querySelector('.mcell-pnl');
        if (mPnl) {
          mPnl.textContent = fmtINR(pnl);
          mPnl.className = 'mcell-pnl font-mono font-bold tabular-nums whitespace-nowrap ' + pnlColorClass(pnl);
        }
        const mPnlChip = card.querySelector('.mcell-pnl-chip');
        if (mPnlChip) mPnlChip.innerHTML = pnlChipHTML(pnlPct);
      }

      // If expanded, update LTP in the expanded view
      const expLtp = document.getElementById('pf-exp-ltp-' + h.symbol);
      if (expLtp) expLtp.textContent = fmtINR(ltp);
    });

    updateHoldingsFooter(list);
    return;
  }

  // Full Build Path
  if (typeof activeHoldingCharts !== 'undefined') {
    Object.keys(activeHoldingCharts).forEach(sym => {
      if (typeof disposeHoldingChart === 'function') disposeHoldingChart(sym);
    });
  }
  tbody.innerHTML = '';
  if (cardsWrap) cardsWrap.innerHTML = '';

  list.forEach(h => {
    const pnl = h.unrealized_pnl || 0;
    const pnlPct = h.pnl_pct || 0;
    const dayChg = h.day_change_pct || 0;
    const ltp = h.live_price || h.avg_buy_price;

    // Flash detection on price tick
    let flashClass = '';
    if (previousHoldingsPrices[h.symbol] !== undefined && previousHoldingsPrices[h.symbol] !== null && previousHoldingsPrices[h.symbol] !== ltp) {
      flashClass = ltp > previousHoldingsPrices[h.symbol] ? 'flash-green' : 'flash-red';
    }
    previousHoldingsPrices[h.symbol] = ltp;

    const isExpanded = expandedRowSymbol === h.symbol;
    const advisory = globalAdvisoryData?.stock_advisories?.find(s => s.symbol === h.symbol || s.company_name.includes(h.symbol));
    const tech = advisory?.technicals || {
      rsi: 35.0, rsi_status: 'Accumulation', stop_loss: (h.avg_buy_price * 0.9).toFixed(2),
      target_1: (h.avg_buy_price * 1.1).toFixed(2), target_2: (h.avg_buy_price * 1.2).toFixed(2),
      pattern: 'Base Consolidation', strategy: 'Positional hold. Maintain risk guardrail.'
    };

    const hasRsi = tech.rsi !== null && tech.rsi !== undefined && !isNaN(Number(tech.rsi));
    const rsiVal = hasRsi ? Number(tech.rsi) : null;
    let rsiStatus = tech.rsi_status || 'Neutral / Range-bound';
    let rsiBadgeColor = 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300';
    if (hasRsi) {
      if (rsiVal < 30) {
        rsiStatus = 'Oversold';
        rsiBadgeColor = 'bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300';
      } else if (rsiVal >= 40 && rsiVal <= 60) {
        rsiStatus = 'Neutral / Range-bound';
        rsiBadgeColor = 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300';
      } else if (rsiVal >= 70) {
        rsiStatus = 'Overbought';
        rsiBadgeColor = 'bg-rose-100 dark:bg-rose-950 text-rose-800 dark:text-rose-300';
      }
    }
    const rsiDisplay = hasRsi ? `RSI ${rsiVal.toFixed(1)} · ${rsiStatus}` : `${rsiStatus}`;

    const slVal = tech.stop_loss || (h.avg_buy_price ? (h.avg_buy_price * 0.90) : null);
    const tsVal = tech.trailing_stop || slVal;
    const t1Val = tech.target_1 || (h.avg_buy_price ? (h.avg_buy_price * 1.14) : null);
    const t2Val = tech.target_2 || (t1Val ? (t1Val * 1.08) : null);

    // 1. DESKTOP ROW
    const row = document.createElement('tr');
    row.id = `pf-row-${h.symbol}`;
    row.dataset.holdingSymbol = h.symbol;
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    row.className = `hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors duration-150 cursor-pointer border-b border-slate-100 dark:border-slate-800/80 ${isExpanded ? 'bg-emerald-50/20 dark:bg-emerald-950/20' : ''}`;
    row.onclick = (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      toggleRowExpand(h.symbol);
    };
    row.onkeydown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleRowExpand(h.symbol);
      }
    };

    row.innerHTML = `
      <td class="px-4 py-3">
        <div class="flex items-center gap-2">
          <button onclick="toggleRowExpand('${h.symbol}')" class="p-0.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition" aria-label="Toggle details">
            <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="w-3.5 h-3.5"></i>
          </button>
          <div class="min-w-0">
            <span class="font-bold text-slate-900 dark:text-white block truncate max-w-[200px] sm:max-w-[260px]" title="${h.company_name}">${h.company_name}</span>
            <div class="text-[10px] text-slate-400 font-mono">${h.symbol} · ${h.exchange}</div>
          </div>
        </div>
      </td>
      <td class="cell-qty px-3 py-3 text-right font-mono text-slate-700 dark:text-slate-300 tabular-nums">${h.quantity}</td>
      <td class="cell-avg px-3 py-3 text-right font-mono text-slate-700 dark:text-slate-300 tabular-nums">${fmtINR(h.avg_buy_price)}</td>
      <td class="cell-ltp px-3 py-3 text-right font-mono font-bold text-slate-900 dark:text-white tabular-nums ${flashClass}" aria-live="polite">
        ${fmtINR(ltp)}
      </td>
      <td class="cell-curval px-3 py-3 text-right font-mono font-bold text-slate-900 dark:text-white tabular-nums" aria-live="polite">${fmtINR(h.current_value)}</td>
      <td class="px-3 py-3 text-right whitespace-nowrap">
        <div class="cell-pnl-val font-mono font-bold tabular-nums ${pnlColorClass(pnl)}">${fmtINR(pnl)}</div>
        <div class="cell-pnl-chip">${pnlChipHTML(pnlPct)}</div>
      </td>
      <td class="cell-daychg px-3 py-3 text-right whitespace-nowrap">
        ${pnlChipHTML(dayChg, true)}
      </td>
      <td class="cell-trend px-2 py-3 text-center">
        ${typeof renderSparkline === 'function' ? renderSparkline(h.trend_closes) : ''}
      </td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <div class="flex items-center justify-end gap-1.5">
          <button onclick="toggleRowExpand('${h.symbol}')" title="AI Technical Diagnostics"
                  class="px-2 py-1 rounded-md text-[10px] font-bold text-indigo-700 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/50 hover:bg-indigo-100 dark:hover:bg-indigo-900/60 border border-indigo-200 dark:border-indigo-800/60 transition cursor-pointer">
            AI Insight
          </button>
          <button onclick="deleteHolding(${h.id}, '${h.symbol}')" title="Delete holding"
                  class="p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition cursor-pointer">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(row);

    // Desktop Inline Row Expand
    if (isExpanded) {
      const expandRow = document.createElement('tr');
      expandRow.id = `pf-expand-${h.symbol}`;
      expandRow.className = 'bg-slate-50/70 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-800';
      expandRow.innerHTML = `
        <td colspan="9" class="p-4 sm:p-5 space-y-3">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200/60 dark:border-slate-800 pb-2.5">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                <i data-lucide="sparkles" class="w-3.5 h-3.5 text-indigo-500"></i> ${h.symbol} Technical Health Diagnosis
              </span>
              <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${rsiBadgeColor}">
                ${rsiDisplay}
              </span>
            </div>
            <div class="text-[11px] text-slate-500 font-mono">
              Pattern: <strong>${tech.pattern || 'Consolidation'}</strong>
            </div>
          </div>

          <!-- Horizontal Price Bar -->
          <div class="space-y-1.5 pt-1">
            <div class="grid grid-cols-2 sm:grid-cols-6 text-center text-[10px] font-mono font-semibold gap-2">
              <div class="text-rose-600 dark:text-rose-400 sm:text-left">
                <span class="block text-[9px] text-slate-400 font-sans">Stop-Loss (ATR)</span>
                ${fmtINR(slVal)}
              </div>
              <div class="text-amber-600 dark:text-amber-400">
                <span class="block text-[9px] text-slate-400 font-sans">Trailing Stop</span>
                ${fmtINR(tsVal)}
              </div>
              <div class="text-slate-600 dark:text-slate-400">
                <span class="block text-[9px] text-slate-400 font-sans">Avg Cost</span>
                ${fmtINR(h.avg_buy_price)}
              </div>
              <div class="text-slate-900 dark:text-white font-bold bg-slate-200/60 dark:bg-slate-800 px-1 py-0.5 rounded">
                <span class="block text-[9px] text-emerald-600 dark:text-emerald-400 font-sans font-bold">LTP</span>
                <span id="pf-exp-ltp-${h.symbol}">${fmtINR(ltp)}</span>
              </div>
              <div class="text-blue-600 dark:text-blue-400">
                <span class="block text-[9px] text-slate-400 font-sans">Target 1 <span class="italic text-[8px] opacity-75">(estimated)</span></span>
                ${fmtINR(t1Val)}
              </div>
              <div class="text-indigo-600 dark:text-indigo-400 sm:text-right">
                <span class="block text-[9px] text-slate-400 font-sans">Target 2 <span class="italic text-[8px] opacity-75">(estimated)</span></span>
                ${fmtINR(t2Val)}
              </div>
            </div>
            <div class="relative h-2 w-full bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden flex shadow-inner">
              <div class="h-full bg-rose-400" style="width: 15%" title="Stop-Loss Zone"></div>
              <div class="h-full bg-amber-400" style="width: 15%" title="Trailing Stop Zone"></div>
              <div class="h-full bg-yellow-400" style="width: 20%" title="Cost Zone"></div>
              <div class="h-full bg-emerald-400" style="width: 25%" title="Target 1 Zone"></div>
              <div class="h-full bg-blue-500" style="width: 25%" title="Target 2 Zone"></div>
            </div>
          </div>

          <!-- AI Action Plan with Markdown Support -->
          <div class="p-3 rounded-lg bg-white dark:bg-[#121826] border border-slate-200/70 dark:border-slate-800 text-[11px] text-slate-700 dark:text-slate-300 leading-relaxed">
            <strong>💡 Action Plan:</strong> ${typeof formatAIMarkdown === 'function' ? formatAIMarkdown(tech.strategy || 'Hold position. Maintain risk guardrail.') : (tech.strategy || '')}
            <p class="text-[10px] text-slate-400 dark:text-slate-500 italic mt-1.5 pt-1.5 border-t border-slate-100 dark:border-slate-800">Mechanical technical levels, not a forecast or investment advice.</p>
          </div>

          <!-- TradingView Lightweight Charts -->
          <div class="p-3 sm:p-4 rounded-xl bg-white dark:bg-[#121826] border border-slate-200/80 dark:border-slate-800 space-y-3">
            <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800/80 pb-2.5">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                  <i data-lucide="line-chart" class="w-3.5 h-3.5 text-indigo-500"></i>
                  <span>Price Action &amp; Momentum (${h.symbol})</span>
                </span>
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50">
                  <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> EMA 20
                </span>
                <span class="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-800/50">
                  <span class="w-1.5 h-1.5 rounded-full bg-purple-500"></span> EMA 50
                </span>
              </div>

              <div class="flex items-center gap-2">
                <div class="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900 text-[10px] font-semibold" role="group" aria-label="Chart style toggle">
                  <button type="button" onclick="toggleHoldingChartType('${h.symbol}', 'candle')" id="btn-chart-type-candle-${h.symbol}" class="px-2 py-0.5 rounded transition ${holdingChartType[h.symbol] !== 'line' ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-xs font-bold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}">
                    Candles
                  </button>
                  <button type="button" onclick="toggleHoldingChartType('${h.symbol}', 'line')" id="btn-chart-type-line-${h.symbol}" class="px-2 py-0.5 rounded transition ${holdingChartType[h.symbol] === 'line' ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-xs font-bold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}">
                    Line
                  </button>
                </div>

                <div class="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900 text-[10px] font-semibold" role="group" aria-label="Time range selector">
                  ${['1m', '3m', '6m', '1y'].map(r => `
                    <button type="button" onclick="setHoldingChartRange('${h.symbol}', '${r}')" id="btn-range-${r}-${h.symbol}" class="px-2 py-0.5 rounded transition ${((holdingChartRange[h.symbol] || '3m') === r) ? 'bg-indigo-600 text-white font-bold' : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'}">
                      ${r.toUpperCase()}
                    </button>
                  `).join('')}
                </div>
              </div>
            </div>

            <div class="relative w-full">
              <div id="holding-chart-loading-${h.symbol}" class="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-[#121826]/80 backdrop-blur-2xs rounded-lg">
                <div class="flex items-center gap-2 text-xs font-semibold text-slate-500">
                  <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-indigo-500"></i>
                  <span>Loading candlestick history &amp; indicators...</span>
                </div>
              </div>

              <div id="holding-chart-msg-${h.symbol}" class="hidden text-center py-10 px-4 space-y-1">
                <p id="holding-chart-msg-text-${h.symbol}" class="text-xs text-slate-500 font-medium"></p>
              </div>

              <div id="holding-chart-main-${h.symbol}" class="w-full h-[260px]" aria-label="${h.symbol} candlestick price chart with EMA 20 and EMA 50" role="img"></div>

              <div class="pt-2 border-t border-slate-100 dark:border-slate-800">
                <div class="flex items-center justify-between text-[10px] font-mono text-slate-400 mb-1">
                  <span>RSI (14) MOMENTUM PANEL</span>
                  <span id="holding-rsi-val-${h.symbol}" class="font-bold text-slate-600 dark:text-slate-300">—</span>
                </div>
                <div id="holding-chart-rsi-${h.symbol}" class="w-full h-[80px]" aria-label="${h.symbol} RSI 14 momentum oscillator chart" role="img"></div>
              </div>
            </div>

            <p id="holding-chart-summary-${h.symbol}" class="sr-only">${h.symbol} technical chart data summary.</p>
          </div>
        </td>
      `;
      tbody.appendChild(expandRow);
    }

    // 2. MOBILE STACKED CARD (< 768px)
    if (cardsWrap) {
      const card = document.createElement('div');
      card.id = `pf-card-${h.symbol}`;
      card.dataset.holdingSymbol = h.symbol;
      card.className = `p-3.5 space-y-2.5 transition ${isExpanded ? 'bg-emerald-50/20 dark:bg-emerald-950/20' : ''}`;
      card.innerHTML = `
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 cursor-pointer" onclick="toggleRowExpand('${h.symbol}')">
            <div class="font-bold text-xs text-slate-900 dark:text-white">${h.company_name}</div>
            <div class="text-[10px] text-slate-400 font-mono">${h.symbol} · ${h.exchange}</div>
          </div>
          <div class="text-right">
            <div class="mcell-ltp font-mono font-bold text-xs text-slate-900 dark:text-white tabular-nums ${flashClass}">${fmtINR(ltp)}</div>
            <div class="mcell-daychg mt-0.5">${pnlChipHTML(dayChg, true)}</div>
          </div>
        </div>

        <div class="flex items-center justify-between text-[11px] pt-1 border-t border-slate-100/80 dark:border-slate-800/60">
          <div class="text-slate-500 font-mono">
            <span>Qty: <strong class="mcell-qty text-slate-700 dark:text-slate-300">${h.quantity}</strong></span> · 
            <span>Avg: <strong class="mcell-avg text-slate-700 dark:text-slate-300">${fmtINR(h.avg_buy_price)}</strong></span>
          </div>
          <div class="text-right whitespace-nowrap">
            <span class="text-slate-400 text-[10px]">P&amp;L:</span>
            <span class="mcell-pnl font-mono font-bold tabular-nums whitespace-nowrap ${pnlColorClass(pnl)}">${fmtINR(pnl)}</span>
            <span class="mcell-pnl-chip whitespace-nowrap">${pnlChipHTML(pnlPct)}</span>
          </div>
        </div>

        <div class="flex items-center justify-between pt-1">
          <button onclick="toggleRowExpand('${h.symbol}')" class="px-2.5 py-1 rounded-md text-[10px] font-bold text-indigo-700 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/50 hover:bg-indigo-100 border border-indigo-200 dark:border-indigo-800/60 transition flex items-center gap-1">
            <i data-lucide="sparkles" class="w-3 h-3 text-indigo-500"></i>
            <span>${isExpanded ? 'Hide Diagnosis' : 'AI Insight'}</span>
            <i data-lucide="${isExpanded ? 'chevron-up' : 'chevron-down'}" class="w-3 h-3"></i>
          </button>
          <button onclick="deleteHolding(${h.id}, '${h.symbol}')" class="p-1 rounded text-slate-400 hover:text-rose-600 transition">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>

        ${isExpanded ? `
          <div class="p-3 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-2 mt-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${rsiBadgeColor}">
                ${rsiDisplay}
              </span>
              <span class="text-[10px] text-slate-500 font-mono">${tech.pattern || 'Consolidation'}</span>
            </div>
            <div class="space-y-1">
              <div class="flex justify-between text-[9px] font-mono text-slate-400 flex-wrap gap-1">
                <span class="text-rose-600">SL: ${fmtINR(slVal)}</span>
                <span class="text-amber-600">Trail: ${fmtINR(tsVal)}</span>
                <span class="text-emerald-600 font-bold">LTP: ${fmtINR(ltp)}</span>
                <span class="text-indigo-600">T1: ${fmtINR(t1Val)} (est)</span>
              </div>
              <div class="h-1.5 w-full bg-slate-200 dark:bg-slate-800 rounded-full flex overflow-hidden">
                <div class="bg-rose-400 h-full" style="width: 20%"></div>
                <div class="bg-amber-400 h-full" style="width: 20%"></div>
                <div class="bg-emerald-400 h-full" style="width: 35%"></div>
                <div class="bg-indigo-400 h-full" style="width: 25%"></div>
              </div>
            </div>
            <p class="text-[10px] text-slate-600 dark:text-slate-300 leading-snug pt-1">
              <strong>Action:</strong> ${typeof formatAIMarkdown === 'function' ? formatAIMarkdown(tech.strategy || 'Hold. Maintain stop loss.') : (tech.strategy || '')}
            </p>
            <p class="text-[9px] text-slate-400 italic text-center pt-1 border-t border-slate-200/60 dark:border-slate-800">Mechanical technical levels, not a forecast or investment advice.</p>

            <!-- Mobile Technical Price Chart -->
            <div class="p-2.5 rounded-lg bg-white dark:bg-[#121826] border border-slate-200/80 dark:border-slate-800 space-y-2 mt-2">
              <div class="flex items-center justify-between gap-1 flex-wrap">
                <div class="inline-flex rounded-md border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900 text-[9px] font-semibold" role="group" aria-label="Mobile chart style toggle">
                  <button type="button" onclick="toggleHoldingChartType('${h.symbol}', 'candle')" id="mbtn-chart-type-candle-${h.symbol}" class="px-1.5 py-0.5 rounded transition ${holdingChartType[h.symbol] !== 'line' ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white font-bold' : 'text-slate-500'}">Candles</button>
                  <button type="button" onclick="toggleHoldingChartType('${h.symbol}', 'line')" id="mbtn-chart-type-line-${h.symbol}" class="px-1.5 py-0.5 rounded transition ${holdingChartType[h.symbol] === 'line' ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white font-bold' : 'text-slate-500'}">Line</button>
                </div>
                <div class="inline-flex rounded-md border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900 text-[9px] font-semibold" role="group" aria-label="Mobile time range selector">
                  ${['1m', '3m', '6m', '1y'].map(r => `
                    <button type="button" onclick="setHoldingChartRange('${h.symbol}', '${r}')" id="mbtn-range-${r}-${h.symbol}" class="px-1.5 py-0.5 rounded transition ${((holdingChartRange[h.symbol] || '3m') === r) ? 'bg-indigo-600 text-white font-bold' : 'text-slate-500'}">
                      ${r.toUpperCase()}
                    </button>
                  `).join('')}
                </div>
              </div>

              <div class="relative w-full">
                <div id="mholding-chart-loading-${h.symbol}" class="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-[#121826]/80 backdrop-blur-2xs rounded-lg">
                  <span class="text-[10px] text-slate-400 flex items-center gap-1"><i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i> Loading...</span>
                </div>
                <div id="mholding-chart-msg-${h.symbol}" class="hidden text-center py-6 text-[10px] text-slate-400"></div>
                <div id="mholding-chart-main-${h.symbol}" class="w-full h-[190px]" aria-label="${h.symbol} mobile candlestick price chart" role="img"></div>
                <div class="pt-1 border-t border-slate-100 dark:border-slate-800">
                  <div id="mholding-chart-rsi-${h.symbol}" class="w-full h-[65px]" aria-label="${h.symbol} mobile RSI momentum chart" role="img"></div>
                </div>
              </div>
              <p id="mholding-chart-summary-${h.symbol}" class="sr-only">${h.symbol} mobile technical chart summary.</p>
            </div>
          </div>
        ` : ''}
      `;
      cardsWrap.appendChild(card);
    }
  });

  updateHoldingsFooter(list);

  // Add Mobile Summary Card at bottom
  if (cardsWrap && list.length > 0) {
    let sumInvested = 0;
    let sumCurrentVal = 0;
    list.forEach(h => {
      const qty = Number(h.quantity) || 0;
      sumInvested += Number(h.invested_value != null ? h.invested_value : (h.avg_buy_price * qty)) || 0;
      sumCurrentVal += Number(h.current_value != null ? h.current_value : (h.live_price ? h.live_price * qty : sumInvested)) || 0;
    });
    const totalPnl = sumCurrentVal - sumInvested;
    const totalPnlPct = sumInvested > 0 ? (totalPnl / sumInvested) * 100 : 0;

    const summaryCard = document.createElement('div');
    summaryCard.className = 'p-4 bg-slate-100/90 dark:bg-slate-900/90 rounded-b-xl space-y-2 border-t border-slate-200 dark:border-slate-800';
    summaryCard.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-xs font-extrabold text-slate-900 dark:text-white flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-emerald-500"></span> Total Portfolio (Till Now)
        </span>
        <span class="text-xs font-mono font-extrabold tabular-nums ${pnlColorClass(totalPnl)}">${fmtINR(totalPnl)} (${fmtPct(totalPnlPct)})</span>
      </div>
      <div class="grid grid-cols-2 gap-2 text-[11px] pt-1 text-slate-600 dark:text-slate-400 font-mono">
        <div>Invested: <strong class="text-slate-900 dark:text-white">${fmtINR(sumInvested)}</strong></div>
        <div>Current: <strong class="text-slate-900 dark:text-white">${fmtINR(sumCurrentVal)}</strong></div>
      </div>
    `;
    cardsWrap.appendChild(summaryCard);
  }

  refreshLucideIcons();
  if (expandedRowSymbol && typeof renderHoldingChart === 'function') {
    renderHoldingChart(expandedRowSymbol);
  }
}

function toggleRowExpand(symbol) {
  if (expandedRowSymbol && typeof disposeHoldingChart === 'function') {
    disposeHoldingChart(expandedRowSymbol);
  }
  expandedRowSymbol = expandedRowSymbol === symbol ? null : symbol;
  renderHoldings(currentPortfolioHoldings, false, true);
}

async function deleteHolding(id, symbol) {
  if (!getAuthToken()) { openLoginModal(); return; }
  if (!confirm(`Remove ${symbol} from your portfolio?`)) return;
  try {
    const res = await fetch(`${API}/holdings/${id}`, { method: 'DELETE', headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      resetPortfolioUI(true);
      openLoginModal();
      return;
    }
    if (res.ok || res.status === 204) {
      if (expandedRowSymbol === symbol) {
        if (typeof disposeHoldingChart === 'function') disposeHoldingChart(symbol);
        expandedRowSymbol = null;
      }
      loadPortfolio();
    } else {
      alert('Failed to delete holding.');
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

// ── Angel One Integration & Diagnostics ──
let currentEgressIp = '';

function openAngelOneDiagModal() {
  const modal = document.getElementById('angelone-diag-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  refreshLucideIcons();
}

function closeAngelOneDiagModal() {
  const modal = document.getElementById('angelone-diag-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

function retryAngelOneSyncFromModal() {
  closeAngelOneDiagModal();
  syncAngelOne();
}

function copyEgressIp() {
  if (!currentEgressIp || currentEgressIp === 'Fetching...' || currentEgressIp === 'Unavailable') return;
  navigator.clipboard.writeText(currentEgressIp).then(() => {
    const copyBtn = document.getElementById('ao-copy-ip-btn');
    if (copyBtn) {
      copyBtn.innerHTML = '<i data-lucide="check" class="w-3 h-3 text-emerald-500"></i><span class="text-emerald-500 font-bold">Copied</span>';
      refreshLucideIcons();
      setTimeout(() => {
        copyBtn.innerHTML = '<i data-lucide="copy" class="w-3 h-3"></i><span>Copy</span>';
        refreshLucideIcons();
      }, 2000);
    }
  }).catch(() => {
    alert('Egress IPv4: ' + currentEgressIp);
  });
}

function showAngelOneSyncErrorModal(detail, diag) {
  let errClass = 'unknown';
  let message = 'An unexpected error occurred while communicating with Angel One SmartAPI.';
  const lastSync = diag ? (diag.last_failure || diag.last_sync) : null;
  let step = (lastSync && (lastSync.step || lastSync.last_step)) ? (lastSync.step || lastSync.last_step) : 'connect';
  let errCode = (lastSync && (lastSync.error_code || lastSync.last_error_code)) ? (lastSync.error_code || lastSync.last_error_code) : '';

  if (typeof detail === 'string') {
    message = detail;
    const low = detail.toLowerCase();
    if (low.includes('rate limit') || low.includes('too many requests')) {
      errClass = 'rate_limited';
    } else if (low.includes('whitelist') || low.includes('ip')) {
      errClass = 'ip_not_whitelisted';
    } else if (low.includes('timed out') || low.includes('timeout') || low.includes('connection')) {
      errClass = 'network_timeout';
    } else if (low.includes('totp')) {
      errClass = 'invalid_totp';
    } else if (low.includes('password') || low.includes('mpin') || low.includes('client code') || low.includes('credential')) {
      errClass = 'invalid_credentials_mpin';
    }
  } else if (detail && typeof detail === 'object') {
    errClass = detail.error_class || errClass;
    message = detail.message || message;
    if (detail.step) step = detail.step;
    if (detail.error_code) errCode = detail.error_code;
  }

  const ip4 = (diag && diag.egress_ipv4) ? diag.egress_ipv4 : 'Unavailable';
  currentEgressIp = ip4;
  const ip4El = document.getElementById('ao-diag-egress-ipv4');
  if (ip4El) ip4El.textContent = ip4;

  const timeOffset = (diag && diag.time_offset_seconds !== null && diag.time_offset_seconds !== undefined)
    ? (diag.time_offset_seconds >= 0 ? `+${diag.time_offset_seconds.toFixed(2)}s` : `${diag.time_offset_seconds.toFixed(2)}s`)
    : 'Unknown';
  const timeEl = document.getElementById('ao-diag-time-offset');
  if (timeEl) timeEl.textContent = timeOffset;

  const timeStatusEl = document.getElementById('ao-diag-time-status');
  if (timeStatusEl) {
    if (diag && diag.time_offset_seconds !== null && Math.abs(diag.time_offset_seconds) > 15) {
      timeStatusEl.textContent = 'High Drift';
      timeStatusEl.className = 'text-[10px] text-rose-600 dark:text-rose-400 font-semibold';
    } else if (diag && diag.time_offset_seconds !== null) {
      timeStatusEl.textContent = 'Sync OK';
      timeStatusEl.className = 'text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold';
    } else {
      timeStatusEl.textContent = 'N/A';
      timeStatusEl.className = 'text-[10px] text-slate-400 font-semibold';
    }
  }

  const renderEnvTag = (elId, isSet) => {
    const el = document.getElementById(elId);
    if (!el) return;
    if (isSet === true) {
      el.innerHTML = '<span class="text-emerald-600 dark:text-emerald-400 font-semibold">✓ Set</span>';
    } else if (isSet === false) {
      el.innerHTML = '<span class="text-rose-600 dark:text-rose-400 font-bold">✗ Missing</span>';
    } else {
      el.innerHTML = '<span class="text-slate-400">--</span>';
    }
  };

  const envObj = diag ? (diag.env_vars || diag.env_status) : null;
  if (envObj) {
    renderEnvTag('ao-diag-env-apikey', envObj.api_key_set);
    renderEnvTag('ao-diag-env-clientcode', envObj.client_id_set !== undefined ? envObj.client_id_set : envObj.client_code_set);
    renderEnvTag('ao-diag-env-password', envObj.password_set);
    renderEnvTag('ao-diag-env-totp', envObj.totp_secret_set);
  } else {
    renderEnvTag('ao-diag-env-apikey', null);
    renderEnvTag('ao-diag-env-clientcode', null);
    renderEnvTag('ao-diag-env-password', null);
    renderEnvTag('ao-diag-env-totp', null);
  }

  const stepEl = document.getElementById('ao-diag-failed-step');
  if (stepEl) stepEl.textContent = step;

  const codeBadge = document.getElementById('ao-diag-code-badge');
  if (codeBadge) codeBadge.textContent = errCode ? `Code: ${errCode}` : `Step: ${step}`;

  const errorConfigs = {
    ip_not_whitelisted: {
      badge: 'IP Not Whitelisted',
      title: 'Server Egress IP Not Whitelisted in SmartAPI',
      steps: [
        `Log in to your Angel One developer dashboard at <a href="https://smartapi.angelone.in" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 font-semibold underline hover:text-blue-700">smartapi.angelone.in</a>.`,
        `Open your API App configuration and navigate to <strong>IP Whitelist</strong>.`,
        `Add this server\'s live egress IPv4 address: <strong class="font-mono text-slate-800 dark:text-slate-200">${ip4}</strong> (click the Copy button in Server Telemetry below).`,
        `Save your settings, wait 1 minute for Angel One\'s security firewall to update, and click <strong>Retry Sync</strong>.`
      ]
    },
    network_timeout: {
      badge: 'Connection Timeout',
      title: 'Connection Timed Out / Firewall Blocked',
      steps: [
        `On cloud hosting servers, Angel One SmartAPI silently drops packets when an IP is unwhitelisted. Ensure <strong class="font-mono text-slate-800 dark:text-slate-200">${ip4}</strong> is added to your IP whitelist at <a href="https://smartapi.angelone.in" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 font-semibold underline hover:text-blue-700">smartapi.angelone.in</a>.`,
        `Confirm this server allows outbound HTTPS connections to <span class="font-mono">apiconnect.angelone.in:443</span>.`,
        `Angel One servers occasionally experience brief latency. Wait 30 seconds and retry.`
      ]
    },
    invalid_credentials_mpin: {
      badge: 'Credentials Invalid',
      title: 'Invalid Client Code or Password/MPIN',
      steps: [
        `Verify your server configuration for <strong>ANGELONE_CLIENT_CODE</strong> and <strong>ANGELONE_PASSWORD</strong>.`,
        `Ensure the MPIN matches the PIN used in your active Angel One mobile app session.`,
        `Verify that your Angel One trading account is active and has not been locked due to repeated incorrect password attempts.`
      ]
    },
    invalid_totp: {
      badge: 'TOTP Authentication Failed',
      title: 'Invalid or Expired TOTP Token',
      steps: [
        `Check server clock drift (currently <strong>${timeOffset}</strong>). TOTP codes are time-sensitive; drift exceeding 15s causes auth tokens to be rejected.`,
        `Verify that <strong>ANGELONE_TOTP_SECRET</strong> configured in your server matches the Base32 2FA secret from your Angel One profile.`,
        `If you reset or regenerated 2FA recently in the Angel One app or portal, update the secret in your server environment.`
      ]
    },
    rate_limited: {
      badge: 'Rate Limit Hit',
      title: 'Angel One API Rate Limit Exceeded',
      steps: [
        `Angel One enforces per-second and per-minute request throughput caps on SmartAPI endpoints.`,
        `Wait 1 to 2 minutes for your API rate-limit window to refresh.`,
        `Avoid triggering rapid consecutive manual sync clicks.`
      ]
    },
    unknown: {
      badge: 'API Error',
      title: 'Angel One SmartAPI Error',
      steps: [
        `Review the error code (<strong>${errCode || 'N/A'}</strong>) and failed step (<strong>${step}</strong>) in the telemetry box below.`,
        `Check the <a href="https://smartapi.angelone.in" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 font-semibold underline hover:text-blue-700">Angel One SmartAPI Developer Forum</a> for any ongoing service maintenance.`,
        `Verify your credentials and server environment settings, then retry.`
      ]
    }
  };

  const cfg = errorConfigs[errClass] || errorConfigs.unknown;
  const titleEl = document.getElementById('ao-diag-cause-title');
  if (titleEl) titleEl.textContent = cfg.title;

  const badgeEl = document.getElementById('ao-diag-cause-badge');
  if (badgeEl) badgeEl.textContent = cfg.badge;

  const msgEl = document.getElementById('ao-diag-cause-msg');
  if (msgEl) msgEl.textContent = message;

  const stepsListEl = document.getElementById('ao-diag-steps-list');
  if (stepsListEl) {
    stepsListEl.innerHTML = cfg.steps.map(s => `<li class="leading-relaxed">${s}</li>`).join('');
  }

  openAngelOneDiagModal();
}

async function syncAngelOne() {
  if (!getAuthToken()) { openLoginModal(); return; }
  const btn = document.getElementById('ao-sync-btn');
  const origHTML = btn.innerHTML;
  btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Syncing...</span>';
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/import/angelone`, { method: 'POST', headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      resetPortfolioUI(true);
      openLoginModal();
      return;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let diag = null;
      try {
        const diagRes = await fetch(`${API}/import/angelone/diagnose`, { headers: getAuthHeaders() });
        if (diagRes.ok) diag = await diagRes.json();
      } catch (dErr) {
        console.warn('Diagnostics fetch failed:', dErr);
      }
      showAngelOneSyncErrorModal(data.detail, diag);
      return;
    }
    alert(`✅ Angel One sync complete!\nCreated: ${data.created}  Updated: ${data.updated}  Skipped: ${data.skipped}`);
    loadPortfolio();
  } catch (err) {
    let diag = null;
    try {
      const diagRes = await fetch(`${API}/import/angelone/diagnose`, { headers: getAuthHeaders() });
      if (diagRes.ok) diag = await diagRes.json();
    } catch (_) {}
    showAngelOneSyncErrorModal({
      error_class: 'network_timeout',
      message: 'Network error communicating with server: ' + err.message,
      error_code: 'CLIENT_NETWORK_ERR',
      step: 'connect'
    }, diag);
  } finally {
    btn.innerHTML = origHTML;
    btn.disabled = false;
    refreshLucideIcons();
  }
}

async function importCSV(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (!getAuthToken()) {
    event.target.value = '';
    openLoginModal();
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  event.target.value = '';
  try {
    const res = await fetch(`${API}/import/csv`, { method: 'POST', headers: getAuthHeaders(), body: formData });
    if (res.status === 401) {
      setAuthToken(null);
      resetPortfolioUI(true);
      openLoginModal();
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 422 && data.detail && data.detail.includes('password-protected')) {
        const pwd = prompt('🔒 This statement is password-protected by your broker.\n\nPlease enter your password (e.g., your PAN in CAPITAL letters):');
        if (pwd && pwd.trim()) {
          const retryForm = new FormData();
          retryForm.append('file', file);
          retryForm.append('password', pwd.trim());
          const retryRes = await fetch(`${API}/import/csv`, { method: 'POST', headers: getAuthHeaders(), body: retryForm });
          if (retryRes.status === 401) {
            setAuthToken(null);
            resetPortfolioUI(true);
            openLoginModal();
            return;
          }
          const retryData = await retryRes.json();
          if (!retryRes.ok) {
            alert('⚠️ Decryption/Import failed: ' + (retryData.detail || JSON.stringify(retryData)));
            return;
          }
          alert(`✅ Statement imported!\nParsed: ${retryData.total_parsed}  Created: ${retryData.created}  Updated: ${retryData.updated}`);
          loadPortfolio();
          return;
        }
        return;
      }
      alert('⚠️ Import failed: ' + (data.detail || JSON.stringify(data)));
      return;
    }
    alert(`✅ Import complete!\nParsed: ${data.total_parsed}  Created: ${data.created}  Updated: ${data.updated}`);
    loadPortfolio();
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

function openAddHoldingModal() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  document.getElementById('add-holding-modal').classList.remove('hidden');
  document.getElementById('add-holding-modal').classList.add('flex');
}

function closeAddHoldingModal() {
  document.getElementById('add-holding-modal').classList.add('hidden');
  document.getElementById('add-holding-modal').classList.remove('flex');
  document.getElementById('add-holding-form').reset();
  document.getElementById('add-holding-error').classList.add('hidden');
}

async function submitAddHolding(e) {
  e.preventDefault();
  const errEl = document.getElementById('add-holding-error');
  errEl.classList.add('hidden');

  const body = {
    symbol: document.getElementById('ah-symbol').value.trim().toUpperCase(),
    company_name: document.getElementById('ah-company').value.trim(),
    exchange: document.getElementById('ah-exchange').value,
    quantity: parseFloat(document.getElementById('ah-qty').value),
    avg_buy_price: parseFloat(document.getElementById('ah-price').value),
    initial_transaction_date: document.getElementById('ah-date').value || null,
  };

  try {
    const res = await fetch(`${API}/holdings`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    });
    if (res.status === 401) {
      setAuthToken(null);
      resetPortfolioUI(true);
      openLoginModal();
      return;
    }
    if (res.ok || res.status === 201) {
      closeAddHoldingModal();
      loadPortfolio();
    } else {
      const data = await res.json();
      errEl.textContent = data.detail || 'Failed to add holding.';
      errEl.classList.remove('hidden');
    }
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
    errEl.classList.remove('hidden');
  }
}

// ── Combined Net Worth ──
async function loadCombinedNetWorth() {
  if (!getAuthToken()) return;
  try {
    const res = await fetch(`${API}/net-worth`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const nw = await res.json();

    // 1. Update Portfolio tab banner
    const pfTotal = document.getElementById('pf-net-worth-total');
    if (pfTotal) pfTotal.textContent = fmtINR(nw.total_net_worth);
    const pfStocks = document.getElementById('pf-net-worth-stocks');
    if (pfStocks) pfStocks.textContent = fmtINR(nw.stocks.current_value);
    const pfMf = document.getElementById('pf-net-worth-mf');
    if (pfMf) pfMf.textContent = fmtINR(nw.mutual_funds.current_value);

    // 2. Update Mutual Funds tab banner
    const mfTotal = document.getElementById('mf-total-net-worth');
    if (mfTotal) mfTotal.textContent = fmtINR(nw.total_net_worth);
    const mfPnlChip = document.getElementById('mf-total-pnl-chip');
    if (mfPnlChip) mfPnlChip.innerHTML = pnlChipHTML(nw.total_pnl_pct);

    const mfStocksVal = document.getElementById('mf-combined-stocks-val');
    if (mfStocksVal) mfStocksVal.textContent = fmtINR(nw.stocks.current_value);
    const mfStocksPct = document.getElementById('mf-combined-stocks-pct');
    if (mfStocksPct) {
      const sPct = nw.total_net_worth > 0 ? (nw.stocks.current_value / nw.total_net_worth * 100) : 0;
      mfStocksPct.textContent = sPct.toFixed(1) + '%';
    }

    const mfFundsVal = document.getElementById('mf-combined-funds-val');
    if (mfFundsVal) mfFundsVal.textContent = fmtINR(nw.mutual_funds.current_value);
    const mfFundsPct = document.getElementById('mf-combined-funds-pct');
    if (mfFundsPct) {
      const fPct = nw.total_net_worth > 0 ? (nw.mutual_funds.current_value / nw.total_net_worth * 100) : 0;
      mfFundsPct.textContent = fPct.toFixed(1) + '%';
    }
  } catch (err) {
    console.warn('Failed to load combined net worth:', err);
  }
}
