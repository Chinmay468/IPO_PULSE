// ==================== MUTUAL FUNDS MODULE ====================

// Load Mutual Funds Summary & Holdings
async function loadMFSummary(silent = false) {
  if (!getAuthToken()) {
    resetMFUI();
    if (!silent) openLoginModal();
    return;
  }

  if (!silent) {
    document.getElementById('mf-loading').classList.remove('hidden');
    document.getElementById('mf-empty').classList.add('hidden');
    document.getElementById('mf-holdings-container').classList.add('hidden');
  }

  try {
    const res = await fetch(`${API}/mf/summary`, { headers: getAuthHeaders() });
    if (res.status === 401) {
      setAuthToken(null);
      resetMFUI();
      if (!silent) openLoginModal();
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Summary Cards
    document.getElementById('mf-invested').textContent = fmtINR(data.total_invested);
    document.getElementById('mf-current-value').textContent = fmtINR(data.current_value);
    document.getElementById('mf-pnl').textContent = fmtINR(data.total_pnl);
    document.getElementById('mf-pnl-chip').innerHTML = pnlChipHTML(data.total_pnl_pct);
    document.getElementById('mf-xirr').textContent = data.overall_xirr != null ? fmtPct(data.overall_xirr) : '—';
    document.getElementById('mf-holdings-count').textContent = `${data.holdings_count} fund${data.holdings_count === 1 ? '' : 's'}`;

    const navDateBadge = document.getElementById('mf-nav-date-badge');
    if (navDateBadge) {
      navDateBadge.textContent = data.nav_as_of_date ? `NAV as of ${fmtMFDate(data.nav_as_of_date)}` : 'NAV as of —';
    }

    const unpricedAlert = document.getElementById('mf-unpriced-alert');
    if (unpricedAlert) {
      if (data.unpriced_count > 0) {
        unpricedAlert.textContent = `⚠️ ${data.unpriced_count} unpriced fund${data.unpriced_count > 1 ? 's' : ''} (excluded from value & XIRR)`;
        unpricedAlert.classList.remove('hidden');
      } else {
        unpricedAlert.classList.add('hidden');
      }
    }

    currentMFHoldings = data.holdings || [];

    if (currentMFHoldings.length === 0) {
      document.getElementById('mf-loading').classList.add('hidden');
      document.getElementById('mf-holdings-container').classList.add('hidden');
      document.getElementById('mf-empty').classList.remove('hidden');
      renderMFDonutCharts([], []);
    } else {
      document.getElementById('mf-loading').classList.add('hidden');
      document.getElementById('mf-empty').classList.add('hidden');
      document.getElementById('mf-holdings-container').classList.remove('hidden');
      renderMFHoldingsTable(currentMFHoldings);
      renderMFDonutCharts(data.category_allocation || [], data.amc_allocation || []);
    }

    // Also refresh combined net worth
    loadCombinedNetWorth();
  } catch (err) {
    console.error('MF summary load failed:', err);
    if (!silent) {
      document.getElementById('mf-loading').classList.add('hidden');
      document.getElementById('mf-empty').classList.remove('hidden');
    }
  } finally {
    refreshLucideIcons();
  }
}

function resetMFUI() {
  document.getElementById('mf-invested').textContent = '—';
  document.getElementById('mf-current-value').textContent = '—';
  document.getElementById('mf-pnl').textContent = '—';
  document.getElementById('mf-pnl-chip').textContent = '—';
  document.getElementById('mf-xirr').textContent = '—';
  document.getElementById('mf-holdings-count').textContent = '0 funds';
  document.getElementById('mf-loading').classList.add('hidden');
  document.getElementById('mf-holdings-container').classList.add('hidden');
  document.getElementById('mf-empty').classList.remove('hidden');
  if (mfCategoryChart) { mfCategoryChart.destroy(); mfCategoryChart = null; }
  if (mfAmcChart) { mfAmcChart.destroy(); mfAmcChart = null; }
  if (mfHistoryLineChart) { mfHistoryLineChart.destroy(); mfHistoryLineChart = null; }
  const chartCard = document.getElementById('mf-nav-chart-card');
  if (chartCard) chartCard.classList.add('hidden');
}

function renderMFHoldingsTable(holdings) {
  const tbody = document.getElementById('mf-tbody');
  if (!tbody) return;

  const sorted = [...holdings].sort((a, b) => {
    let valA = a[currentMFSortCol];
    let valB = b[currentMFSortCol];
    if (typeof valA === 'string') valA = valA.toLowerCase();
    if (typeof valB === 'string') valB = valB.toLowerCase();
    if (valA == null) return 1;
    if (valB == null) return -1;
    if (valA < valB) return currentMFSortAsc ? -1 : 1;
    if (valA > valB) return currentMFSortAsc ? 1 : -1;
    return 0;
  });

  tbody.innerHTML = sorted.map(h => {
    const isUnpriced = h.latest_nav == null;

    return `
      <tr class="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition">
        <td class="px-4 py-3">
          <div class="font-bold text-slate-900 dark:text-white leading-snug">${escapeHtml(h.scheme_name)}</div>
          <div class="flex flex-wrap items-center gap-1.5 mt-1">
            ${h.amc ? `<span class="text-[10px] font-medium px-1.5 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${escapeHtml(h.amc)}</span>` : ''}
            ${h.category ? `<span class="text-[10px] font-medium px-1.5 py-0.2 rounded bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-400 border border-indigo-200/60 dark:border-indigo-800/40">${escapeHtml(h.category)}</span>` : ''}
            ${h.scheme_code ? `<span class="text-[9px] font-mono text-slate-400">#${escapeHtml(h.scheme_code)}</span>` : ''}
          </div>
        </td>
        <td class="px-3 py-3 text-center font-mono text-slate-500 dark:text-slate-400">${escapeHtml(h.folio_masked || '—')}</td>
        <td class="px-3 py-3 text-right font-mono tabular-nums text-slate-900 dark:text-slate-100">${h.units.toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
        <td class="px-3 py-3 text-right font-mono tabular-nums text-slate-600 dark:text-slate-400">${fmtINR(h.avg_nav)}</td>
        <td class="px-3 py-3 text-right">
          ${!isUnpriced ? `
            <div class="font-mono tabular-nums font-bold text-slate-900 dark:text-white">${fmtINR(h.latest_nav)}</div>
            <div class="text-[10px] text-slate-400 mt-0.5 flex items-center justify-end gap-1">
              <span>${h.latest_nav_date ? fmtMFDate(h.latest_nav_date) : ''}</span>
              ${h.is_nav_stale ? `<span class="text-[9px] font-bold px-1 py-0.2 rounded bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-800">STALE</span>` : ''}
            </div>
          ` : `
            <span class="text-[10px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 px-1.5 py-0.5 rounded">Unpriced</span>
          `}
        </td>
        <td class="px-3 py-3 text-right font-mono tabular-nums font-bold text-slate-900 dark:text-white">
          ${!isUnpriced ? fmtINR(h.current_value) : '—'}
        </td>
        <td class="px-3 py-3 text-right">
          ${!isUnpriced ? `
            <div class="font-mono tabular-nums font-bold ${pnlColorClass(h.pnl)}">${fmtINR(h.pnl)}</div>
            <div class="mt-0.5">${pnlChipHTML(h.pnl_pct)}</div>
          ` : '—'}
        </td>
        <td class="px-3 py-3 text-right font-mono tabular-nums">
          ${h.xirr != null ? `
            <span class="font-bold ${h.xirr >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}">${fmtPct(h.xirr)}</span>
          ` : `<span class="text-slate-400">—</span>`}
        </td>
        <td class="px-4 py-3 text-right">
          <div class="flex items-center justify-end gap-1.5">
            <button onclick="toggleSchemeChart(${h.scheme_id}, '${escapeHtml(h.scheme_name).replace(/'/g, "\\'")}')" title="Historical NAV Chart"
              class="p-1.5 rounded-lg text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/60 transition cursor-pointer">
              <i data-lucide="line-chart" class="w-3.5 h-3.5"></i>
            </button>
            <button onclick="openMFEditModal(${h.id}, ${h.units}, '${escapeHtml(h.folio_masked || '').replace(/'/g, "\\'")}', '${escapeHtml(h.scheme_name).replace(/'/g, "\\'")}')" title="Edit Holding"
              class="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer">
              <i data-lucide="edit-2" class="w-3.5 h-3.5"></i>
            </button>
            <button onclick="deleteMFHolding(${h.id}, '${escapeHtml(h.scheme_name).replace(/'/g, "\\'")}')" title="Delete Holding"
              class="p-1.5 rounded-lg text-rose-500 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/60 transition cursor-pointer">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  // Footers
  const totInvested = sorted.reduce((sum, h) => sum + (h.invested || 0), 0);
  const totValue = sorted.reduce((sum, h) => sum + (h.current_value || 0), 0);
  const totPnl = sorted.reduce((sum, h) => sum + (h.pnl || 0), 0);
  const pnlPct = totInvested > 0 ? (totPnl / totInvested * 100) : 0;

  const tfootInvested = document.getElementById('mf-tfoot-invested');
  if (tfootInvested) tfootInvested.textContent = fmtINR(totInvested);
  const tfootValue = document.getElementById('mf-tfoot-value');
  if (tfootValue) tfootValue.textContent = fmtINR(totValue);
  const tfootPnl = document.getElementById('mf-tfoot-pnl');
  if (tfootPnl) {
    tfootPnl.className = `px-3 py-3.5 text-right font-mono tabular-nums ${pnlColorClass(totPnl)}`;
    tfootPnl.textContent = `${fmtINR(totPnl)} (${fmtPct(pnlPct)})`;
  }

  refreshLucideIcons();
}

function filterMFTable() {
  const q = (document.getElementById('mf-search-input')?.value || '').toLowerCase().trim();
  if (!q) {
    renderMFHoldingsTable(currentMFHoldings);
    return;
  }
  const filtered = currentMFHoldings.filter(h => {
    return (h.scheme_name || '').toLowerCase().includes(q) ||
           (h.amc || '').toLowerCase().includes(q) ||
           (h.category || '').toLowerCase().includes(q) ||
           (h.scheme_code || '').toLowerCase().includes(q) ||
           (h.folio_masked || '').toLowerCase().includes(q);
  });
  renderMFHoldingsTable(filtered);
}

function sortMFTable(col) {
  if (currentMFSortCol === col) {
    currentMFSortAsc = !currentMFSortAsc;
  } else {
    currentMFSortCol = col;
    currentMFSortAsc = (col === 'scheme_name');
  }

  ['scheme_name', 'units', 'avg_nav', 'latest_nav', 'current_value', 'pnl', 'xirr'].forEach(c => {
    const el = document.getElementById('mf-sort-' + c);
    if (el) {
      el.textContent = (c === currentMFSortCol) ? (currentMFSortAsc ? '▲' : '▼') : '↕';
    }
  });

  filterMFTable();
}

// Allocation Donut Charts (Category & AMC)
function renderMFDonutCharts(categoryAlloc, amcAlloc) {
  if (typeof Chart === 'undefined') return;

  const isDark = document.documentElement.classList.contains('dark');
  const textColor = isDark ? '#94a3b8' : '#64748b';

  const catColors = ['#6366f1', '#10b981', '#f59e0b', '#ec4899', '#3b82f6', '#8b5cf6', '#14b8a6', '#06b6d4'];
  const amcColors = ['#10b981', '#3b82f6', '#6366f1', '#f59e0b', '#ec4899', '#06b6d4', '#84cc16', '#a855f7'];

  // Category Donut
  const catEmpty = document.getElementById('mf-category-empty');
  const catBox = document.getElementById('mf-category-chart-box');
  const catCanvas = document.getElementById('mf-category-donut-chart');

  if (!categoryAlloc || categoryAlloc.length === 0) {
    if (catEmpty) catEmpty.classList.remove('hidden');
    if (catBox) catBox.classList.add('hidden');
    if (mfCategoryChart) { mfCategoryChart.destroy(); mfCategoryChart = null; }
  } else if (catCanvas) {
    if (catEmpty) catEmpty.classList.add('hidden');
    if (catBox) catBox.classList.remove('hidden');
    if (mfCategoryChart) mfCategoryChart.destroy();

    mfCategoryChart = new Chart(catCanvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: categoryAlloc.map(c => c.name),
        datasets: [{
          data: categoryAlloc.map(c => c.value),
          backgroundColor: catColors.slice(0, categoryAlloc.length),
          borderWidth: 2,
          borderColor: isDark ? '#121826' : '#ffffff'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              boxWidth: 8,
              boxHeight: 8,
              padding: 8,
              font: { size: 10, family: 'Inter, system-ui' },
              color: textColor
            }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                const val = ctx.raw;
                const pct = categoryAlloc[ctx.dataIndex]?.percentage || 0;
                return ` ${ctx.label}: ${fmtINR(val)} (${pct.toFixed(1)}%)`;
              }
            }
          }
        }
      }
    });
  }

  // AMC Donut
  const amcEmpty = document.getElementById('mf-amc-empty');
  const amcBox = document.getElementById('mf-amc-chart-box');
  const amcCanvas = document.getElementById('mf-amc-donut-chart');

  if (!amcAlloc || amcAlloc.length === 0) {
    if (amcEmpty) amcEmpty.classList.remove('hidden');
    if (amcBox) amcBox.classList.add('hidden');
    if (mfAmcChart) { mfAmcChart.destroy(); mfAmcChart = null; }
  } else if (amcCanvas) {
    if (amcEmpty) amcEmpty.classList.add('hidden');
    if (amcBox) amcBox.classList.remove('hidden');
    if (mfAmcChart) mfAmcChart.destroy();

    mfAmcChart = new Chart(amcCanvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: amcAlloc.map(a => a.name),
        datasets: [{
          data: amcAlloc.map(a => a.value),
          backgroundColor: amcColors.slice(0, amcAlloc.length),
          borderWidth: 2,
          borderColor: isDark ? '#121826' : '#ffffff'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              boxWidth: 8,
              boxHeight: 8,
              padding: 8,
              font: { size: 10, family: 'Inter, system-ui' },
              color: textColor
            }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                const val = ctx.raw;
                const pct = amcAlloc[ctx.dataIndex]?.percentage || 0;
                return ` ${ctx.label}: ${fmtINR(val)} (${pct.toFixed(1)}%)`;
              }
            }
          }
        }
      }
    });
  }
}

// Historical NAV Line Chart per Scheme
async function toggleSchemeChart(schemeId, schemeName) {
  const card = document.getElementById('mf-nav-chart-card');
  if (!card) return;

  activeMFSchemeId = schemeId;
  card.classList.remove('hidden');
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  document.getElementById('mf-chart-scheme-name').textContent = schemeName;
  document.getElementById('mf-chart-loading').classList.remove('hidden');
  document.getElementById('mf-history-chart-box').classList.add('hidden');

  try {
    const res = await fetch(`${API}/mf/${schemeId}/history`, { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const points = data.history || [];

    document.getElementById('mf-chart-loading').classList.add('hidden');
    const box = document.getElementById('mf-history-chart-box');
    box.classList.remove('hidden');

    const canvas = document.getElementById('mf-history-line-chart');
    if (!canvas) return;

    if (mfHistoryLineChart) {
      mfHistoryLineChart.destroy();
      mfHistoryLineChart = null;
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';
    const textColor = isDark ? '#94a3b8' : '#64748b';

    const labels = points.map(p => fmtMFDate(p.date));
    const navValues = points.map(p => p.nav);

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 240);
    gradient.addColorStop(0, 'rgba(99, 102, 241, 0.25)');
    gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');

    mfHistoryLineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'NAV (₹)',
          data: navValues,
          borderColor: '#6366f1',
          backgroundColor: gradient,
          borderWidth: 2,
          fill: true,
          tension: 0.2,
          pointRadius: points.length > 50 ? 0 : 2,
          pointHoverRadius: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 8 }
          },
          y: {
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              font: { size: 10 },
              callback: (val) => '₹' + Number(val).toFixed(2)
            }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ` NAV: ₹${Number(ctx.raw).toFixed(4)}`
            }
          }
        }
      }
    });
  } catch (err) {
    console.error('Failed to load scheme NAV history:', err);
    document.getElementById('mf-chart-loading').innerHTML = '<span class="text-rose-500 font-semibold text-xs">Failed to load NAV trajectory.</span>';
  }
}

function closeMFNavChart() {
  const card = document.getElementById('mf-nav-chart-card');
  if (card) card.classList.add('hidden');
  if (mfHistoryLineChart) {
    mfHistoryLineChart.destroy();
    mfHistoryLineChart = null;
  }
  activeMFSchemeId = null;
}

// Sync Daily AMFI NAVs
async function syncMFNavs() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }

  const btn = document.getElementById('mf-sync-nav-btn');
  const icon = document.getElementById('mf-sync-nav-icon');
  if (icon) icon.classList.add('animate-spin');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`${API}/mf/sync-navs`, {
      method: 'POST',
      headers: getAuthHeaders()
    });
    if (res.ok) {
      await loadMFSummary(true);
    } else {
      console.warn('Sync NAVs returned status:', res.status);
    }
  } catch (err) {
    console.error('Sync NAVs error:', err);
  } finally {
    if (icon) icon.classList.remove('animate-spin');
    if (btn) btn.disabled = false;
    refreshLucideIcons();
  }
}

// CAS Import Modal
function openMFCASModal() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const modal = document.getElementById('mf-cas-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('mf-cas-form').reset();
  document.getElementById('mf-cas-error').classList.add('hidden');
  document.getElementById('mf-cas-success').classList.add('hidden');
  refreshLucideIcons();
}

function closeMFCASModal() {
  const modal = document.getElementById('mf-cas-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.getElementById('mf-cas-form').reset();
}

async function submitMFCASImport(e) {
  e.preventDefault();
  const fileInput = document.getElementById('mf-cas-file');
  const passInput = document.getElementById('mf-cas-password');
  const errEl = document.getElementById('mf-cas-error');
  const succEl = document.getElementById('mf-cas-success');
  const btnText = document.getElementById('mf-cas-btn-text');
  const spinner = document.getElementById('mf-cas-spinner');
  const submitBtn = document.getElementById('mf-cas-submit-btn');

  errEl.classList.add('hidden');
  succEl.classList.add('hidden');

  if (!fileInput.files || fileInput.files.length === 0) {
    errEl.textContent = 'Please select a CAS PDF file.';
    errEl.classList.remove('hidden');
    return;
  }

  const file = fileInput.files[0];
  if (file.size > 10 * 1024 * 1024) {
    errEl.textContent = 'File size exceeds 10 MB limit.';
    errEl.classList.remove('hidden');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  if (passInput.value.trim()) {
    formData.append('password', passInput.value.trim());
  }

  submitBtn.disabled = true;
  btnText.textContent = 'Parsing in memory...';
  spinner.classList.remove('hidden');

  try {
    const res = await fetch(`${API}/mf/import/cas`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: formData
    });

    if (res.status === 401) {
      setAuthToken(null);
      closeMFCASModal();
      openLoginModal();
      return;
    }

    const data = await res.json();
    if (res.ok) {
      succEl.textContent = data.message || `Import complete: ${data.transactions_imported} transactions imported.`;
      succEl.classList.remove('hidden');
      setTimeout(() => {
        closeMFCASModal();
        loadMFSummary();
        loadPortfolio(true);
      }, 1200);
    } else {
      errEl.textContent = data.detail || 'Failed to parse CAS statement.';
      errEl.classList.remove('hidden');
    }
  } catch (err) {
    errEl.textContent = 'Network error while uploading CAS statement: ' + err.message;
    errEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    btnText.textContent = 'Import Statement';
    spinner.classList.add('hidden');
    refreshLucideIcons();
  }
}

// Manual Holding Modal (Add / Edit)
function openMFManualModal() {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const modal = document.getElementById('mf-manual-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('mf-manual-title').textContent = 'Add Mutual Fund';
  document.getElementById('mf-manual-form').reset();
  document.getElementById('mfm-holding-id').value = '';
  document.getElementById('mfm-error').classList.add('hidden');
  document.getElementById('mfm-extra-fields').classList.remove('hidden');
  document.getElementById('mfm-avg-nav-box').classList.remove('hidden');
  document.getElementById('mfm-scheme-name').disabled = false;
  document.getElementById('mfm-submit-btn').textContent = 'Save Holding';
  refreshLucideIcons();
}

function openMFEditModal(id, units, folio, schemeName) {
  if (!getAuthToken()) {
    openLoginModal();
    return;
  }
  const modal = document.getElementById('mf-manual-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('mf-manual-title').textContent = 'Edit Mutual Fund Units';
  document.getElementById('mf-manual-form').reset();
  document.getElementById('mfm-holding-id').value = id;
  document.getElementById('mfm-error').classList.add('hidden');
  document.getElementById('mfm-scheme-name').value = schemeName || '';
  document.getElementById('mfm-scheme-name').disabled = true;
  document.getElementById('mfm-folio').value = folio || '';
  document.getElementById('mfm-units').value = units;
  document.getElementById('mfm-extra-fields').classList.add('hidden');
  document.getElementById('mfm-avg-nav-box').classList.add('hidden');
  document.getElementById('mfm-submit-btn').textContent = 'Update Holding';
  refreshLucideIcons();
}

function closeMFManualModal() {
  const modal = document.getElementById('mf-manual-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.getElementById('mf-manual-form').reset();
}

async function submitMFManualHolding(e) {
  e.preventDefault();
  const errEl = document.getElementById('mfm-error');
  errEl.classList.add('hidden');

  const holdingId = document.getElementById('mfm-holding-id').value;
  const units = parseFloat(document.getElementById('mfm-units').value);
  const folio = document.getElementById('mfm-folio').value.trim() || null;

  try {
    if (holdingId) {
      // Edit existing holding units / folio
      const res = await fetch(`${API}/mf/holdings/${holdingId}`, {
        method: 'PUT',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ units: units, folio_masked: folio })
      });
      if (res.ok) {
        closeMFManualModal();
        loadMFSummary();
      } else {
        const data = await res.json();
        errEl.textContent = data.detail || 'Failed to update holding.';
        errEl.classList.remove('hidden');
      }
    } else {
      // Add new holding
      const schemeName = document.getElementById('mfm-scheme-name').value.trim();
      const schemeCode = document.getElementById('mfm-scheme-code').value.trim() || null;
      const amc = document.getElementById('mfm-amc').value.trim() || null;
      const category = document.getElementById('mfm-category').value || null;
      const avgNav = parseFloat(document.getElementById('mfm-avg-nav').value) || 0;

      const res = await fetch(`${API}/mf/holdings`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          scheme_name: schemeName,
          scheme_code: schemeCode,
          amc: amc,
          category: category,
          folio_masked: folio,
          units: units,
          avg_nav: avgNav
        })
      });
      if (res.ok) {
        closeMFManualModal();
        loadMFSummary();
      } else {
        const data = await res.json();
        errEl.textContent = data.detail || 'Failed to add holding.';
        errEl.classList.remove('hidden');
      }
    }
  } catch (err) {
    errEl.textContent = 'Network error: ' + err.message;
    errEl.classList.remove('hidden');
  }
}

async function deleteMFHolding(id, name) {
  if (!confirm(`Are you sure you want to delete "${name}" and all its transactions?`)) return;

  try {
    const res = await fetch(`${API}/mf/holdings/${id}`, {
      method: 'DELETE',
      headers: getAuthHeaders()
    });
    if (res.ok) {
      loadMFSummary();
      if (activeMFSchemeId) closeMFNavChart();
    } else {
      const data = await res.json();
      alert(data.detail || 'Failed to delete holding.');
    }
  } catch (err) {
    alert('Error deleting holding: ' + err.message);
  }
}
