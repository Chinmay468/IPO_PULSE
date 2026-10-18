// ==================== IPO MASTER DATA & LISTINGS ====================

async function loadIpos(silent = false) {
  try {
    const res = await fetch('/api/v1/ipos?limit=100');
    const data = await res.json();
    allIpos = data.items || [];
    updateStats(allIpos);
    applyFilters();
    loadScraperFreshness();
  } catch (err) {
    if (!silent) {
      console.error("Failed to load IPOs:", err);
    }
  }
}

async function loadScraperFreshness() {
  const syncTimeEl = document.getElementById('discovery-last-sync-time');
  const staleBannerEl = document.getElementById('discovery-stale-banner');
  const dotEl = document.getElementById('discovery-status-dot');
  if (!syncTimeEl) return;

  try {
    const res = await fetch('/api/v1/scraper/status');
    if (!res.ok) return;
    const data = await res.json();

    if (data.last_full_sync) {
      let s = String(data.last_full_sync).trim();
      if (s.includes('T') && !s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z';
      const d = new Date(s);
      const timeStr = d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      const ageSec = data.last_sync_age_seconds;
      let ageStr = '';
      if (ageSec !== null && ageSec !== undefined) {
        if (ageSec < 60) ageStr = 'just now';
        else if (ageSec < 3600) ageStr = `${Math.round(ageSec / 60)}m ago`;
        else if (ageSec < 86400) ageStr = `${Math.round(ageSec / 3600)}h ago`;
        else ageStr = `${Math.round(ageSec / 86400)}d ago`;
      }
      syncTimeEl.textContent = `${timeStr} (${ageStr})`;
    } else {
      syncTimeEl.textContent = 'Never (Awaiting initial sync)';
    }

    if (data.is_discovery_stale) {
      if (staleBannerEl) {
        staleBannerEl.classList.remove('hidden');
        if (data.stale_warning) {
          const msgEl = document.getElementById('discovery-stale-msg');
          if (msgEl) msgEl.textContent = data.stale_warning;
        }
      }
      if (dotEl) {
        dotEl.classList.remove('bg-[var(--accent-green)]');
        dotEl.classList.add('bg-[var(--accent-vermilion)]');
      }
    } else {
      if (staleBannerEl) staleBannerEl.classList.add('hidden');
      if (dotEl) {
        dotEl.classList.remove('bg-[var(--accent-vermilion)]');
        dotEl.classList.add('bg-[var(--accent-green)]');
      }
    }

    // GMP Quality Alert Banner (Step 9)
    const gmpAlertEl = document.getElementById('gmp-quality-alert-banner');
    if (gmpAlertEl) {
      if (data.gmp_quality && data.gmp_quality.alert_active) {
        gmpAlertEl.classList.remove('hidden');
        const gmpMsgEl = document.getElementById('gmp-quality-alert-msg');
        if (gmpMsgEl && data.gmp_quality.message) {
          gmpMsgEl.textContent = data.gmp_quality.message;
        }
      } else {
        gmpAlertEl.classList.add('hidden');
      }
    }

    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    console.warn("Failed to check scraper freshness:", err);
  }
}

function updateStats(items) {
  const activeItems = items.filter(i => i.status !== 'LISTED');
  const live = activeItems.filter(i => i.status === 'LIVE').length;
  const upcoming = activeItems.filter(i => i.status === 'UPCOMING').length;
  const apply = activeItems.filter(i => i.score && (i.score.recommendation === 'APPLY' || i.score.recommendation === 'STRONG APPLY')).length;
  document.getElementById('stat-live').textContent = live;
  document.getElementById('stat-upcoming').textContent = upcoming;
  document.getElementById('stat-apply').textContent = apply;
}

function applyFilters() {
  const search = document.getElementById('search-input').value.toLowerCase().trim();
  const status = document.getElementById('filter-status').value;
  const rec = document.getElementById('filter-rec').value;
  const type = document.getElementById('filter-type')?.value || '';

  const filtered = allIpos.filter(ipo => {
    if (ipo.status === 'LISTED') return false;
    const matchesSearch = !search || ipo.company_name.toLowerCase().includes(search) || ipo.symbol.toLowerCase().includes(search);
    const matchesStatus = !status || ipo.status === status;
    const matchesRec = !rec || (ipo.score && ipo.score.recommendation === rec);
    const matchesType = !type || (ipo.ipo_type && ipo.ipo_type.toUpperCase() === type.toUpperCase());
    return matchesSearch && matchesStatus && matchesRec && matchesType;
  });

  renderIpos(filtered);
}

function formatIpoDayLabel(ipo) {
  if (ipo.dates_tba) return 'Dates to be announced';
  if (ipo.day_label) return ipo.day_label;
  if (!ipo.open_date || !ipo.close_date || ipo.is_dates_unavailable) return 'Dates to be announced';
  const open = new Date(ipo.open_date + 'T00:00:00+05:30');
  const close = new Date(ipo.close_date + 'T23:59:59+05:30');
  const now = new Date();
  if (close < open) return 'Dates unavailable';
  if (now < open) {
    const diffDays = Math.ceil((open - now) / 86400000);
    return diffDays === 1 ? 'Opens in 1 day' : `Opens in ${diffDays} days`;
  }
  if (ipo.listing_date) {
    const listD = new Date(ipo.listing_date + 'T00:00:00+05:30');
    if (now >= listD) {
      return `Listed on ${listD.getDate()} ${listD.toLocaleString('en-US', { month: 'short' })}`;
    }
  }
  if (now > close) {
    return `Closed on ${close.getDate()} ${close.toLocaleString('en-US', { month: 'short' })}`;
  }
  let curr = new Date(open);
  let totalB = 0;
  let elapsedB = 0;
  while (curr <= close) {
    const day = curr.getDay();
    if (day !== 0 && day !== 6) totalB++;
    curr.setDate(curr.getDate() + 1);
  }
  curr = new Date(open);
  while (curr <= now && curr <= close) {
    const day = curr.getDay();
    if (day !== 0 && day !== 6) elapsedB++;
    curr.setDate(curr.getDate() + 1);
  }
  const y = Math.max(1, totalB);
  const x = Math.max(1, Math.min(elapsedB, y));
  return `Day ${x} of ${y}`;
}

function renderIpos(items) {
  const container = document.getElementById('ipos-container');
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<div class="col-span-full py-12 text-center text-slate-400 text-xs">No IPOs found matching the selected filters.</div>';
    return;
  }

  const now = new Date();
  const filterStatus = document.getElementById('filter-status')?.value;

  // Group items: if UPCOMING, sort announced by open_date ASC, then TBA at the end.
  // Otherwise standard items, then TBA at the end.
  let standard = [];
  let tba = [];
  if (filterStatus === 'UPCOMING') {
    standard = items.filter(i => !i.dates_tba && i.open_date);
    tba = items.filter(i => i.dates_tba || !i.open_date);
    standard.sort((a, b) => new Date(a.open_date) - new Date(b.open_date));
    tba.sort((a, b) => a.company_name.localeCompare(b.company_name));
  } else {
    standard = items.filter(i => !i.dates_tba && i.open_date);
    tba = items.filter(i => i.dates_tba || !i.open_date);
  }

  function renderCard(ipo) {
    const rec = ipo.score ? ipo.score.recommendation : 'NEUTRAL';
    const confidence = (ipo.score && ipo.score.rationale && ipo.score.rationale.confidence != null) ? ipo.score.rationale.confidence : 1.0;
    const isInsufficientData = rec === 'INSUFFICIENT DATA' || confidence < 0.50;
    const isClosed = ipo.status === 'CLOSED';
    const isListed = ipo.status === 'LISTED';
    const isClosedOrListed = isClosed || isListed;

    const score = ipo.score ? ipo.score.composite_score : null;
    // Step 4: Below 50% confidence, NO numeric score is displayed
    const scoreDisplay = (!isInsufficientData && score !== null) ? score.toFixed(1) : '—';

    // Consensus GMP (Step 4 & Step 10)
    const consensus = ipo.consensus_gmp;
    let gmpDisplay = 'N/A';
    let sourceBadge = '';
    let disagreeBadge = '';
    let extremeGmpBadge = '';
    let gmpTooltip = '';

    // Step 7: Extreme GMP (>50% of issue price)
    const basePrice = ipo.issue_price || ipo.price_band_high || ipo.price_band_low;
    if (consensus && consensus.gmp_amount !== null && basePrice && basePrice > 0) {
      const gmpRatio = consensus.gmp_amount / basePrice;
      const gmpPct = consensus.gmp_percentage != null ? consensus.gmp_percentage : (gmpRatio * 100.0);
      if (gmpRatio > 0.50 || gmpPct > 50.0) {
        extremeGmpBadge = `<span class="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-600 dark:text-amber-400 font-bold border border-amber-500/30" title="Consensus GMP is >50% of issue price">Verify before relying</span>`;
      }
    }

    if (consensus && consensus.gmp_amount !== null && consensus.status === 'fresh') {
      gmpDisplay = `+₹${consensus.gmp_amount} (${consensus.gmp_percentage.toFixed(1)}%)`;
      const count = consensus.sources_count || 1;
      sourceBadge = `<span class="text-[9px] px-1 py-0.2 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 font-medium">${count} source${count > 1 ? 's' : ''}</span>`;
      if (consensus.sources_disagree) {
        disagreeBadge = `<span class="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-600 dark:text-amber-400 font-bold border border-amber-500/30" title="Sources differ by >30%">⚠️ Disagree</span>`;
      }
      if (consensus.sources && consensus.sources.length > 0) {
        gmpTooltip = consensus.sources.map(s => {
          let tStr = '';
          if (s.recorded_at) {
            const dt = new Date(s.recorded_at);
            const diffMin = Math.round(Math.max(0, Date.now() - dt.getTime()) / 60000);
            tStr = diffMin < 60 ? `${diffMin}m ago` : `${Math.round(diffMin/60)}h ago`;
          }
          return `${s.source}: ₹${s.gmp_amount} (${s.gmp_percentage ? s.gmp_percentage.toFixed(1) : 0}%)${tStr ? ' ' + tStr : ''}`;
        }).join(' | ');
      }
    } else if (ipo.latest_gmp && ipo.latest_gmp.gmp_amount !== null) {
      gmpDisplay = `+₹${ipo.latest_gmp.gmp_amount} (${ipo.latest_gmp.gmp_percentage.toFixed(1)}%)`;
      sourceBadge = `<span class="text-[9px] px-1 py-0.2 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 font-medium">1 source</span>`;
      gmpTooltip = `${ipo.latest_gmp.source}: ₹${ipo.latest_gmp.gmp_amount} (${ipo.latest_gmp.gmp_percentage.toFixed(1)}%)`;
    }

    const sub = ipo.latest_subscription;
    const subLabel = isClosedOrListed ? 'Final Subscription' : 'Subscribed';
    let totalSubDisplay = sub ? `${sub.total_multiple.toFixed(1)}x` : (ipo.status === 'UPCOMING' ? 'Awaiting Bids' : '0.0x');
    if (isClosedOrListed && ipo.listing_info && ipo.listing_info.listing_gain_pct != null) {
      const gSign = ipo.listing_info.listing_gain_pct >= 0 ? '+' : '';
      totalSubDisplay += ` · Listing: ${gSign}${ipo.listing_info.listing_gain_pct.toFixed(1)}%`;
    }

    const isSME = (ipo.ipo_type || '').toUpperCase() === 'SME';
    const typeBadge = isSME
      ? `<span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/70 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60 uppercase tracking-wider">SME</span>`
      : `<span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60 uppercase tracking-wider">MAINBOARD</span>`;

    // Timeline label
    const dayLabel = `<span class="text-[9px] text-slate-500 dark:text-slate-400 font-medium">${formatIpoDayLabel(ipo)}</span>`;

    // Updated N min ago (find the most recent timestamp among all available data points)
    let updatedLabel = '';
    let isStale = false;
    const candidateTimestamps = [
      ipo.score && ipo.score.calculated_at,
      ipo.latest_gmp && ipo.latest_gmp.recorded_at,
      ipo.latest_subscription && ipo.latest_subscription.recorded_at,
      ipo.updated_at,
      ipo.fetched_at
    ].filter(Boolean);

    let scrapeTime = null;
    let maxMs = 0;
    for (const raw of candidateTimestamps) {
      let s = String(raw).trim();
      if (s.includes('T') && !s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) {
        s += 'Z';
      }
      const d = new Date(s);
      if (!isNaN(d.getTime()) && d.getTime() > maxMs) {
        maxMs = d.getTime();
        scrapeTime = d;
      }
    }

    if (scrapeTime) {
      const diffMs = Math.max(0, now - scrapeTime);
      const diffMin = Math.round(diffMs / 60000);
      isStale = diffMin > 45 && ipo.status === 'LIVE';
      const timeAgo = diffMin < 1
        ? 'just now'
        : diffMin < 60
          ? `${diffMin}m ago`
          : diffMin < 1440
            ? `${Math.round(diffMin / 60)}h ago`
            : `${Math.round(diffMin / 1440)}d ago`;
      updatedLabel = `<span class="text-[9px] text-slate-400 dark:text-slate-500">Updated ${timeAgo}</span>`;
    }

    // Stale warning badge (only when LIVE and >45 min)
    const staleWarning = isStale
      ? `<div class="flex items-center gap-1 text-[9px] font-semibold text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800/60 rounded px-2 py-0.5">
           <svg class="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>
           Data may be stale (&gt;45 min)
         </div>`
      : '';

    // SME note
    const smeNote = isSME
      ? `<p class="text-[9px] text-purple-600 dark:text-purple-400 leading-snug mt-0.5">SME: higher minimum bid, lower liquidity</p>`
      : '';

    // Apply button logic (Step 7: Suppressed for Closed / Listed)
    let applyBtn = '';
    if (ipo.can_apply && !isClosedOrListed) {
      if (rec === 'AVOID' || rec === 'INSUFFICIENT DATA') {
        applyBtn = '';
      } else if (rec === 'NEUTRAL') {
        applyBtn = `<a href="${ipo.angelone_apply_url || ('/api/v1/ipos/' + ipo.id + '/apply/angelone')}" target="_blank"
          class="px-2.5 py-1 rounded text-xs font-semibold border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition">Apply ↗</a>`;
      } else {
        applyBtn = `<a href="${ipo.angelone_apply_url || ('/api/v1/ipos/' + ipo.id + '/apply/angelone')}" target="_blank"
          class="px-2.5 py-1 rounded text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white transition">Apply ↗</a>`;
      }
    } else {
      applyBtn = `<span class="text-[10px] text-slate-400 font-medium">${isClosedOrListed ? 'Closed' : 'Upcoming'}</span>`;
    }

    // Status pill
    let statusClass = 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
    if (ipo.status === 'LIVE') {
      statusClass = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 font-semibold';
    } else if (ipo.status === 'UPCOMING') {
      statusClass = 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 font-semibold';
    }

    // Step 4 & 5: Score section rendering
    let scoreSection = '';
    if (isClosed) {
      scoreSection = `
        <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300">Closed</span>
            <div class="flex items-center text-xs">
              <span class="text-[10px] text-slate-400 font-medium mr-1.5">Score at close:</span>
              <span class="font-mono font-bold text-slate-800 dark:text-white">${scoreDisplay}</span>
            </div>
          </div>
        </div>
      `;
    } else if (isInsufficientData) {
      const missingList = (ipo.score && ipo.score.rationale && ipo.score.rationale.missing_inputs) || [];
      const missingText = missingList.length > 0 ? `Missing: ${missingList.join(', ')}` : 'Inputs pending';
      scoreSection = `
        <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-INSUFFICIENT_DATA">Insufficient data</span>
            <span class="font-mono text-xs font-bold text-slate-400">—</span>
          </div>
          <div class="text-[9px] text-slate-500 dark:text-slate-400 mt-1">${missingText}</div>
        </div>
      `;
    } else {
      const recClean = rec.replace(/[ ,]/g, '_').replace(/_+/g, '_');
      scoreSection = `
        <div class="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${recClean}">${rec}</span>
            <span class="font-mono text-xs font-bold text-slate-800 dark:text-white">${scoreDisplay} <span class="text-[9px] text-slate-400">/100</span></span>
          </div>
        </div>
      `;
    }

    return `
      <div class="bg-white dark:bg-[#121826] rounded-xl border border-[#E8EAEE] dark:border-[#1F2937] shadow-soft p-4 flex flex-col justify-between space-y-3 hover:border-slate-300 dark:hover:border-slate-700 transition">
        <div class="space-y-2">
          <div class="flex justify-between items-start gap-1">
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${ipo.symbol}</span>
              ${typeBadge}
            </div>
            <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 ${statusClass}">${ipo.status}</span>
          </div>
          <div>
            <h4 class="font-bold text-xs text-slate-900 dark:text-white line-clamp-1" title="${ipo.company_name}">${ipo.company_name}</h4>
            ${smeNote}
          </div>

          ${staleWarning}

          ${scoreSection}

          <div class="grid grid-cols-2 gap-2 text-[11px]">
            <div class="p-2 rounded bg-slate-50 dark:bg-slate-900" title="${gmpTooltip || 'Consensus GMP'}">
              <div class="flex items-center justify-between gap-1 mb-0.5">
                <span class="text-[10px] text-slate-400">GMP</span>
                <div class="flex items-center gap-1 flex-wrap">${sourceBadge}${disagreeBadge}${extremeGmpBadge}</div>
              </div>
              <strong class="font-mono text-emerald-600 dark:text-emerald-400">${gmpDisplay}</strong>
            </div>
            <div class="p-2 rounded bg-slate-50 dark:bg-slate-900">
              <span class="text-[10px] text-slate-400 block">${subLabel}</span>
              <strong class="font-mono text-slate-800 dark:text-white">${totalSubDisplay}</strong>
            </div>
          </div>

          <p class="text-[8.5px] text-slate-400 dark:text-slate-500 leading-tight">GMP is unofficial and can change anytime; not investment advice.</p>

          <div class="flex items-center justify-between text-[9px] text-slate-400">
            ${dayLabel}
            ${updatedLabel}
          </div>
        </div>

        <div class="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <button onclick="openModal(${ipo.id})" class="text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition cursor-pointer">Analysis ➔</button>
          ${applyBtn}
        </div>
      </div>
    `;
  }

  let html = standard.map(ipo => renderCard(ipo)).join('');
  if (tba.length > 0) {
    html += `
      <div class="col-span-full py-2.5 px-3.5 my-1 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 rounded-xl flex items-center justify-between">
        <span>Dates Not Yet Announced (${tba.length} Issues · DRHP Filed)</span>
        <span class="text-[10px] font-normal lowercase tracking-normal text-slate-400">awaiting exchange schedule</span>
      </div>
    `;
    html += tba.map(ipo => renderCard(ipo)).join('');
  }

  container.innerHTML = html;
  if (window.lucide) window.lucide.createIcons();
}

// ── Modal Details (IPO) ──
function populateModalDetails(data) {
  if (!data) return;

  // Source & Updated
  const sourceName = data.source || 'Chittorgarh';
  let timeAgo = '';
  const rawTime = data.fetched_at || (data.score && data.score.calculated_at) || data.updated_at;
  if (rawTime) {
    let s = String(rawTime).trim();
    if (s.includes('T') && !s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z';
    const d = new Date(s);
    if (!isNaN(d.getTime())) {
      const diffMin = Math.round(Math.max(0, Date.now() - d.getTime()) / 60000);
      timeAgo = diffMin < 1 ? 'just now' : diffMin < 60 ? `${diffMin}m ago` : diffMin < 1440 ? `${Math.round(diffMin / 60)}h ago` : `${Math.round(diffMin / 1440)}d ago`;
    }
  }
  const sourceMetaEl = document.getElementById('modal-source-meta');
  if (sourceMetaEl) {
    const updatedStr = timeAgo ? ` · updated ${timeAgo}` : '';
    const srcLink = data.source_url ? `<a href="${data.source_url}" target="_blank" class="hover:underline text-blue-600 dark:text-blue-400">${sourceName} ↗</a>` : sourceName;
    sourceMetaEl.innerHTML = `Source: ${srcLink}${updatedStr} · Algorithmic Analysis`;
  }

  // Data Incomplete Banner
  const incompleteBanner = document.getElementById('modal-incomplete-banner');
  if (incompleteBanner) {
    if (data.data_incomplete) {
      incompleteBanner.classList.remove('hidden');
    } else {
      incompleteBanner.classList.add('hidden');
    }
  }

  // Listing Performance (for Listed IPOs)
  const listingSec = document.getElementById('modal-listing-container');
  const lPrice = (data.listing_info && data.listing_info.listing_price) || data.listing_price;
  const issuePrice = data.issue_price || data.price_band_high || data.price_band_low;
  let lGain = (data.listing_info && data.listing_info.listing_gain_pct != null) ? data.listing_info.listing_gain_pct : null;
  if (lGain == null && lPrice && issuePrice && issuePrice > 0) {
    lGain = Math.round(((lPrice - issuePrice) / issuePrice) * 1000) / 10;
  }
  if (listingSec) {
    if (lPrice != null || lGain != null || data.status === 'LISTED') {
      listingSec.classList.remove('hidden');
      const ipEl = document.getElementById('modal-listing-issue-price');
      if (ipEl) ipEl.textContent = issuePrice ? `₹${issuePrice}` : '—';
      const lpEl = document.getElementById('modal-listing-price');
      if (lpEl) lpEl.textContent = lPrice ? `₹${lPrice}` : '—';
      const lgEl = document.getElementById('modal-listing-gain');
      if (lgEl) {
        if (lGain != null) {
          const sign = lGain > 0 ? '+' : '';
          lgEl.textContent = `${sign}${lGain}%`;
          lgEl.className = `font-mono ${lGain >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`;
        } else {
          lgEl.textContent = '—';
          lgEl.className = 'font-mono text-slate-400';
        }
      }
    } else {
      listingSec.classList.add('hidden');
    }
  }

  // Broker Reviews Breakdown
  const reviewsSec = document.getElementById('modal-reviews-container');
  if (reviewsSec) {
    const revs = data.reviews_summary;
    if (revs && (revs.apply || revs.may_apply || revs.neutral || revs.avoid)) {
      reviewsSec.classList.remove('hidden');
      const total = (revs.apply || 0) + (revs.may_apply || 0) + (revs.neutral || 0) + (revs.avoid || 0);
      const totalEl = document.getElementById('modal-reviews-total');
      if (totalEl) totalEl.textContent = `${total} Total Reviews`;
      const appEl = document.getElementById('modal-reviews-apply');
      if (appEl) appEl.textContent = revs.apply || 0;
      const mayEl = document.getElementById('modal-reviews-may-apply');
      if (mayEl) mayEl.textContent = revs.may_apply || 0;
      const neuEl = document.getElementById('modal-reviews-neutral');
      if (neuEl) neuEl.textContent = revs.neutral || 0;
      const avdEl = document.getElementById('modal-reviews-avoid');
      if (avdEl) avdEl.textContent = revs.avoid || 0;
    } else {
      reviewsSec.classList.add('hidden');
    }
  }

  // Anchor Investors
  const anchorSec = document.getElementById('modal-anchors-container');
  if (anchorSec) {
    const anchors = data.anchor_investors || [];
    if (anchors.length > 0) {
      anchorSec.classList.remove('hidden');
      const totEl = document.getElementById('modal-anchors-total');
      if (totEl) totEl.textContent = `${anchors.length} Institutional Investors`;
      const listEl = document.getElementById('modal-anchors-list');
      if (listEl) {
        listEl.innerHTML = anchors.map(a => `
          <div class="flex items-center justify-between p-2 rounded bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800">
            <span class="font-medium text-slate-800 dark:text-slate-200 line-clamp-1">${a.investor}</span>
            <div class="text-right shrink-0 font-mono text-[10px]">
              ${a.amount ? `<strong class="text-slate-900 dark:text-white">₹${a.amount} Cr</strong>` : ''}
              ${a.lock_in_end ? `<span class="text-slate-400 block text-[9px]">Lock-in: ${a.lock_in_end}</span>` : ''}
            </div>
          </div>
        `).join('');
      }
    } else {
      anchorSec.classList.add('hidden');
    }
  }

  // Official Documents (DRHP / RHP)
  const docsSec = document.getElementById('modal-docs-container');
  if (docsSec) {
    const docs = data.documents || [];
    if (docs.length > 0) {
      docsSec.classList.remove('hidden');
      const listEl = document.getElementById('modal-docs-list');
      if (listEl) {
        listEl.innerHTML = docs.map(d => `
          <a href="${d.url}" target="_blank" rel="noopener noreferrer"
             class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition border border-slate-200 dark:border-slate-700">
            <span>📄 ${d.type || 'Document'}</span>
            <span class="text-[9px] text-slate-400">↗</span>
          </a>
        `).join('');
      }
    } else {
      docsSec.classList.add('hidden');
    }
  }

  // Apply button in modal: hide for CLOSED / LISTED
  const modalApplyBtn = document.getElementById('modal-angelone-btn');
  if (modalApplyBtn) {
    const isClosedOrListed = (data.status === 'CLOSED' || data.status === 'LISTED');
    if (data.can_apply && !isClosedOrListed && data.status === 'LIVE' && data.score && data.score.recommendation !== 'AVOID' && data.score.recommendation !== 'INSUFFICIENT DATA') {
      modalApplyBtn.classList.remove('hidden');
      modalApplyBtn.href = data.angelone_apply_url || ('/api/v1/ipos/' + data.id + '/apply/angelone');
      modalApplyBtn.textContent = 'Apply via Angel One ↗';
    } else {
      modalApplyBtn.classList.add('hidden');
    }
  }
}

function openModal(ipoId) {
  const ipo = allIpos.find(i => i.id === ipoId);
  if (!ipo || !ipo.score) return;

  document.getElementById('modal-company-name').textContent = ipo.company_name;
  document.getElementById('modal-symbol').textContent = ipo.symbol;
  
  const isSME = (ipo.ipo_type || '').toUpperCase() === 'SME';
  const typeBadge = isSME
    ? `<span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/70 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60 uppercase tracking-wider">SME</span>`
    : `<span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60 uppercase tracking-wider">MAINBOARD</span>`;
  const typeContainer = document.getElementById('modal-ipo-type');
  if (typeContainer) typeContainer.innerHTML = typeBadge;

  const rec = ipo.score.recommendation;
  const confidence = (ipo.score.rationale && ipo.score.rationale.confidence != null) ? ipo.score.rationale.confidence : 1.0;
  const isInsufficient = rec === 'INSUFFICIENT DATA' || confidence < 0.50;
  const isClosed = ipo.status === 'CLOSED';
  const badge = document.getElementById('modal-rec-badge');

  if (isInsufficient) {
    document.getElementById('modal-score').textContent = '—';
    badge.textContent = 'Insufficient data';
    badge.className = 'px-2.5 py-1 rounded-lg font-bold text-xs badge-INSUFFICIENT_DATA';
  } else if (isClosed) {
    document.getElementById('modal-score').textContent = ipo.score.composite_score;
    badge.textContent = 'Closed';
    badge.className = 'px-2.5 py-1 rounded-lg font-bold text-xs bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300';
  } else {
    document.getElementById('modal-score').textContent = ipo.score.composite_score;
    const recClean = rec.replace(/[ ,]/g, '_').replace(/_+/g, '_');
    badge.textContent = rec;
    badge.className = `px-2.5 py-1 rounded-lg font-bold text-xs badge-${recClean}`;
  }

  function updateModalBreakdownBars(gmp, sub, val, struct, composite) {
    const gmpNum = Number(gmp) || 0;
    const subNum = Number(sub) || 0;
    const valNum = Number(val) || 0;
    const structNum = Number(struct) || 0;
    const totalNum = Number(composite) || (gmpNum + subNum + valNum + structNum);

    const totalEl = document.getElementById('modal-breakdown-total');
    if (totalEl) totalEl.textContent = `${totalNum.toFixed(1)} / 100`;

    const gmpSeg = document.getElementById('modal-breakdown-gmp-segment');
    if (gmpSeg) gmpSeg.style.width = `${Math.min(35, gmpNum)}%`;
    const subSeg = document.getElementById('modal-breakdown-sub-segment');
    if (subSeg) subSeg.style.width = `${Math.min(30, subNum)}%`;
    const valSeg = document.getElementById('modal-breakdown-val-segment');
    if (valSeg) valSeg.style.width = `${Math.min(20, valNum)}%`;
    const structSeg = document.getElementById('modal-breakdown-struct-segment');
    if (structSeg) structSeg.style.width = `${Math.min(15, structNum)}%`;

    const gmpVal = document.getElementById('modal-breakdown-gmp-val');
    if (gmpVal) gmpVal.textContent = gmpNum.toFixed(1);
    const subVal = document.getElementById('modal-breakdown-sub-val');
    if (subVal) subVal.textContent = subNum.toFixed(1);
    const valVal = document.getElementById('modal-breakdown-val-val');
    if (valVal) valVal.textContent = valNum.toFixed(1);
    const structVal = document.getElementById('modal-breakdown-struct-val');
    if (structVal) structVal.textContent = structNum.toFixed(1);

    document.getElementById('modal-gmp-score').textContent = `${gmpNum.toFixed(1)} / 35`;
    document.getElementById('modal-gmp-bar').style.width = `${(gmpNum / 35) * 100}%`;
    document.getElementById('modal-sub-score').textContent = `${subNum.toFixed(1)} / 30`;
    document.getElementById('modal-sub-bar').style.width = `${(subNum / 30) * 100}%`;
    document.getElementById('modal-val-score').textContent = `${valNum.toFixed(1)} / 20`;
    document.getElementById('modal-val-bar').style.width = `${(valNum / 20) * 100}%`;
    document.getElementById('modal-struct-score').textContent = `${structNum.toFixed(1)} / 15`;
    document.getElementById('modal-struct-bar').style.width = `${(structNum / 15) * 100}%`;
  }

  updateModalBreakdownBars(
    ipo.score.gmp_score,
    ipo.score.subscription_score,
    ipo.score.valuation_score,
    ipo.score.structure_score,
    ipo.score.composite_score
  );

  function renderFinancialStats(item) {
    // Rev Growth
    const revEl = document.getElementById('modal-rev-growth');
    if (revEl) {
      if (item.revenue_growth_yoy != null) {
        if (item.revenue_growth_yoy < 0) {
          revEl.textContent = `Declined ${Math.abs(item.revenue_growth_yoy)}%`;
        } else {
          revEl.textContent = `+${item.revenue_growth_yoy}%`;
        }
      } else {
        revEl.textContent = '—';
      }
    }

    // PAT Growth
    const patEl = document.getElementById('modal-pat-growth');
    if (patEl) {
      const isSwungLoss = (item.pat_growth_yoy != null && item.pat_growth_yoy <= -100) || (item.pat_margin_pct != null && item.pat_margin_pct < 0);
      if (isSwungLoss) {
        patEl.textContent = 'Swung to a loss';
      } else if (item.pat_growth_yoy != null) {
        if (item.pat_growth_yoy < 0) {
          patEl.textContent = `Declined ${Math.abs(item.pat_growth_yoy)}%`;
        } else {
          patEl.textContent = `+${item.pat_growth_yoy}%`;
        }
      } else {
        patEl.textContent = '—';
      }
    }

    // P/E Ratio
    const peEl = document.getElementById('modal-pe-ratio');
    if (peEl) {
      const isLossMaking = (item.eps != null && item.eps < 0) || (item.pat_margin_pct != null && item.pat_margin_pct < 0) || (item.ronw != null && item.ronw < 0) || (item.pe_ratio != null && item.pe_ratio <= 0);
      if (isLossMaking) {
        peEl.textContent = 'Not Meaningful';
      } else if (item.pe_ratio != null && item.pe_ratio > 0) {
        peEl.textContent = `${item.pe_ratio}x`;
      } else {
        peEl.textContent = '—';
      }
    }

    // Debt to Equity
    const deEl = document.getElementById('modal-debt-equity');
    if (deEl) {
      deEl.textContent = item.debt_to_equity ? `${item.debt_to_equity}x` : '—';
    }
  }

  renderFinancialStats(ipo);

  const rationale = ipo.score.rationale || {};
  const pos = rationale.positive_factors || ["Sound issue fundamentals and valuation."];
  const rsk = rationale.risk_factors || ["Subject to listing day broader market sentiment."];
  document.getElementById('modal-positives').innerHTML = pos.map(p => `<li>• ${p}</li>`).join('');
  document.getElementById('modal-risks').innerHTML = rsk.map(r => `<li>• ${r}</li>`).join('');

  populateModalDetails(ipo);

  document.getElementById('score-modal').classList.remove('hidden');
  refreshLucideIcons();

  // Render initial IPO charts state
  if (typeof renderIpoAnalysisCharts === 'function') {
    renderIpoAnalysisCharts(ipo);
  }

  // Fetch full details
  fetch(`/api/v1/ipos/${ipoId}`)
    .then(r => r.ok ? r.json() : null)
    .then(detail => {
      if (detail) {
        renderFinancialStats(detail);
        populateModalDetails(detail);
        if (typeof renderIpoAnalysisCharts === 'function') {
          renderIpoAnalysisCharts(detail);
        }
      }
    })
    .catch(err => console.warn('IPO detail history fetch warning:', err));

  fetch(`/api/v1/ipos/${ipoId}/score/breakdown`)
    .then(r => r.ok ? r.json() : null)
    .then(bd => {
      if (bd && bd.pillars) {
        updateModalBreakdownBars(
          bd.pillars.gmp.score,
          bd.pillars.subscription.score,
          bd.pillars.valuation.score,
          bd.pillars.structure.score,
          bd.composite_score
        );
        if (bd.positive_factors && bd.positive_factors.length) {
          document.getElementById('modal-positives').innerHTML = bd.positive_factors.map(p => `<li>• ${p}</li>`).join('');
        }
        if (bd.risk_factors && bd.risk_factors.length) {
          document.getElementById('modal-risks').innerHTML = bd.risk_factors.map(r => `<li>• ${r}</li>`).join('');
        }
      }
    })
    .catch(err => console.warn('Breakdown fetch warning:', err));
}

function closeModal() {
  document.getElementById('score-modal').classList.add('hidden');
  if (typeof ipoGmpChart !== 'undefined' && ipoGmpChart) {
    ipoGmpChart.destroy();
    ipoGmpChart = null;
  }
  if (typeof ipoSubChart !== 'undefined' && ipoSubChart) {
    ipoSubChart.destroy();
    ipoSubChart = null;
  }
}

// ── Dropdown UI Helpers ──
function closeAllDropdowns() {
  document.querySelectorAll('.custom-dropdown > div[id$="-menu"]').forEach(m => m.classList.add('hidden'));
  const compPopover = document.getElementById('company-picker-popover');
  if (compPopover) compPopover.classList.add('hidden');
}

function toggleDropdown(type) {
  const menu = document.getElementById(`filter-${type}-menu`);
  const isHidden = menu.classList.contains('hidden');
  closeAllDropdowns();
  if (isHidden) menu.classList.remove('hidden');
}

function selectDropdownOption(type, value, label) {
  const hiddenInput = document.getElementById(`filter-${type}`);
  if (hiddenInput) hiddenInput.value = value;
  const labelEl = document.getElementById(`filter-${type}-label`);
  if (labelEl) labelEl.textContent = label;
  closeAllDropdowns();
  applyFilters();
}

// ==================== IPO ALLOTMENT CHECKER & PER-REGISTRAR ROUTING ====================
let allotmentIposList = [];
let selectedAllotmentIpo = null;
let allotmentHighlightedIndex = -1;
let allotmentFilteredItems = [];

const DEFAULT_REGISTRAR_EXTERNAL_URLS = {
  'LINKINTIME': 'https://in.mpms.mufg.com/Initial_Offer/public-issues.html',
  'KFINTECH': 'https://ipostatus.kfintech.com/',
  'BIGSHARE': 'https://ipo.bigshareonline.com/IPO_Status.html',
  'SKYLINE': 'https://www.skylinerta.com/ipo.php',
  'CAMEO': 'https://ipo.cameoindia.com/',
  'PURVA': 'https://www.purvashare.com/queries/',
  'MAASHITLA': 'https://maashitla.com/allotment-status/',
};

function formatRegistrarDisplay(regCode) {
  if (!regCode) return 'Registrar Unknown';
  const clean = String(regCode).toUpperCase().trim();
  const map = {
    'LINKINTIME': 'Link Intime',
    'KFINTECH': 'KFintech',
    'BIGSHARE': 'Bigshare Services',
    'SKYLINE': 'Skyline Financial',
    'CAMEO': 'Cameo Corporate',
    'PURVA': 'Purva Sharegistry',
    'MAASHITLA': 'Maashitla Securities',
    'OTHER': 'Other Registrar'
  };
  return map[clean] || regCode;
}

function formatAllotmentDate(dateStr) {
  if (!dateStr) return 'Date TBA';
  try {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    }
    return dateStr;
  } catch (e) {
    return dateStr;
  }
}

function getIpoComboboxGroup(ipo, todayStr) {
  const today = new Date(todayStr);

  // 1. Open now
  if (ipo.status === 'LIVE' || (ipo.open_date && ipo.close_date && ipo.open_date <= todayStr && todayStr <= ipo.close_date)) {
    return 'Open now';
  }

  // 2. Allotment this week (-3 to +7 days)
  if (ipo.allotment_date) {
    const allotDate = new Date(ipo.allotment_date);
    const diffDays = Math.round((allotDate - today) / (1000 * 60 * 60 * 24));
    if (diffDays >= -3 && diffDays <= 7) {
      return 'Allotment this week';
    }
  }

  // 3. Recent (dates within last 30 days)
  if (ipo.allotment_date) {
    const allotDate = new Date(ipo.allotment_date);
    const diffDays = Math.round((allotDate - today) / (1000 * 60 * 60 * 24));
    if (diffDays >= -30 && diffDays < -3) {
      return 'Recent';
    }
  }
  if (ipo.close_date) {
    const closeDate = new Date(ipo.close_date);
    const diffDays = Math.round((closeDate - today) / (1000 * 60 * 60 * 24));
    if (diffDays >= -30 && diffDays <= 0) {
      return 'Recent';
    }
  }
  if (ipo.listing_date) {
    const listDate = new Date(ipo.listing_date);
    const diffDays = Math.round((listDate - today) / (1000 * 60 * 60 * 24));
    if (diffDays >= -30 && diffDays <= 0) {
      return 'Recent';
    }
  }

  // 4. Older
  return 'Older';
}

async function loadRegistrarCompanies() {
  await loadAllotmentIpos();
}

async function loadAllotmentIpos() {
  const dropdownContent = document.getElementById('allotment-dropdown-content');
  if (dropdownContent && (!allotmentIposList || allotmentIposList.length === 0)) {
    dropdownContent.innerHTML = '<div class="py-4 text-center text-xs text-slate-400">Loading IPOs from database...</div>';
  }

  try {
    const res = await fetch('/api/v1/allotment/ipos?limit=300');
    if (res.ok) {
      const data = await res.json();
      allotmentIposList = data.ipos || [];
      if (allotmentIposList.length === 0 && data.message) {
        if (dropdownContent) {
          dropdownContent.innerHTML = `<div class="py-4 text-center text-xs text-slate-400">${data.message}</div>`;
        }
        return;
      }
    }
  } catch (err) {
    console.error('Failed to load allotment IPOs from database:', err);
  }

  // Render dropdown with current input or initial full list
  const currentVal = document.getElementById('allotment-combobox-input')?.value || '';
  filterAndRenderAllotmentDropdown(currentVal);
}

function openAllotmentCombobox() {
  const popover = document.getElementById('allotment-combobox-dropdown');
  const input = document.getElementById('allotment-combobox-input');
  if (popover) {
    popover.classList.remove('hidden');
    input?.setAttribute('aria-expanded', 'true');
  }
  if (!allotmentIposList || allotmentIposList.length === 0) {
    loadAllotmentIpos();
  } else {
    filterAndRenderAllotmentDropdown(input?.value || '');
  }
}

function closeAllotmentCombobox() {
  const popover = document.getElementById('allotment-combobox-dropdown');
  const input = document.getElementById('allotment-combobox-input');
  if (popover) {
    popover.classList.add('hidden');
    input?.setAttribute('aria-expanded', 'false');
  }
  allotmentHighlightedIndex = -1;
}

function handleAllotmentComboboxInput(val) {
  const clearBtn = document.getElementById('allotment-combobox-clear');
  if (clearBtn) {
    if (val && val.trim().length > 0) {
      clearBtn.classList.remove('hidden');
    } else {
      clearBtn.classList.add('hidden');
    }
  }
  openAllotmentCombobox();
  filterAndRenderAllotmentDropdown(val);
}

function clearAllotmentCombobox() {
  const input = document.getElementById('allotment-combobox-input');
  const clearBtn = document.getElementById('allotment-combobox-clear');
  const ipoIdInput = document.getElementById('allotment-selected-ipo-id');
  const compSelect = document.getElementById('allotment-company-select');
  const card = document.getElementById('allotment-selected-card');
  const banner = document.getElementById('allotment-before-date-banner');
  const inlineForm = document.getElementById('allotment-inline-form');
  const extCard = document.getElementById('allotment-external-card');
  const resultBox = document.getElementById('allotment-result');

  if (input) input.value = '';
  if (clearBtn) clearBtn.classList.add('hidden');
  if (ipoIdInput) ipoIdInput.value = '';
  if (compSelect) compSelect.value = '';
  if (card) card.classList.add('hidden');
  if (banner) banner.classList.add('hidden');
  if (inlineForm) inlineForm.classList.add('hidden');
  if (extCard) extCard.classList.add('hidden');
  if (resultBox) {
    resultBox.classList.add('hidden');
    resultBox.innerHTML = '';
  }

  selectedAllotmentIpo = null;
  allotmentHighlightedIndex = -1;
  openAllotmentCombobox();
  filterAndRenderAllotmentDropdown('');
  input?.focus();
}

function filterAndRenderAllotmentDropdown(query) {
  const dropdownContent = document.getElementById('allotment-dropdown-content');
  if (!dropdownContent) return;

  const q = (query || '').toLowerCase().trim();
  const todayStr = new Date().toISOString().slice(0, 10);

  // Filter IPOs
  let filtered = allotmentIposList;
  if (q.length > 0) {
    filtered = allotmentIposList.filter(ipo =>
      (ipo.company_name && ipo.company_name.toLowerCase().includes(q)) ||
      (ipo.symbol && ipo.symbol.toLowerCase().includes(q)) ||
      (ipo.registrar_name && ipo.registrar_name.toLowerCase().includes(q))
    );
  }

  if (filtered.length === 0) {
    dropdownContent.innerHTML = `
      <div class="py-4 text-center text-xs text-slate-400">
        No IPOs found matching "${query}"
      </div>
    `;
    allotmentFilteredItems = [];
    allotmentHighlightedIndex = -1;
    return;
  }

  // Group filtered IPOs
  const groups = {
    'Open now': [],
    'Allotment this week': [],
    'Recent': [],
    'Older': []
  };

  filtered.forEach(ipo => {
    const group = getIpoComboboxGroup(ipo, todayStr);
    groups[group].push(ipo);
  });

  // Build flattened list for keyboard indexing
  allotmentFilteredItems = [];
  let html = '';
  let globalIdx = 0;

  const groupMeta = [
    { key: 'Open now', label: 'Open Now', badge: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/60' },
    { key: 'Allotment this week', label: 'Allotment This Week', badge: 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-400 border border-blue-200 dark:border-blue-800/60' },
    { key: 'Recent', label: 'Recent Issues', badge: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800/60' },
    { key: 'Older', label: 'Older / Archived', badge: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400' }
  ];

  groupMeta.forEach(({ key, label, badge }) => {
    const items = groups[key];
    if (items && items.length > 0) {
      html += `
        <div class="pt-2 pb-1 px-2">
          <div class="flex items-center justify-between mb-1">
            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400 px-1">${label}</span>
            <span class="text-[9px] font-bold px-1.5 py-0.2 rounded-full ${badge}">${items.length}</span>
          </div>
          <div class="space-y-0.5">
      `;

      items.forEach(ipo => {
        const itemIdx = globalIdx++;
        allotmentFilteredItems.push(ipo);
        const isSelected = selectedAllotmentIpo && selectedAllotmentIpo.id === ipo.id;
        const regDisplay = formatRegistrarDisplay(ipo.registrar_name);
        const dateDisplay = formatAllotmentDate(ipo.allotment_date);

        html += `
          <div id="allotment-item-${itemIdx}" role="option" aria-selected="${isSelected}"
               onclick="selectAllotmentIpo(${ipo.id})"
               class="allotment-option-item w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs cursor-pointer transition select-none ${isSelected ? 'bg-blue-50 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 font-bold' : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/70'}">
            <div class="min-w-0 flex-1 pr-2">
              <div class="font-semibold truncate leading-tight">${ipo.company_name}</div>
              <div class="text-[10px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                <span class="font-mono">${ipo.symbol}</span>
                <span>•</span>
                <span class="uppercase">${ipo.status}</span>
              </div>
            </div>
            <div class="text-right shrink-0">
              <span class="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700/60">
                ${regDisplay}
              </span>
              <div class="text-[10px] text-slate-400 mt-0.5 font-mono">
                ${dateDisplay}
              </div>
            </div>
          </div>
        `;
      });

      html += `</div></div>`;
    }
  });

  dropdownContent.innerHTML = html;
  allotmentHighlightedIndex = -1;
}

function handleAllotmentComboboxKeydown(e) {
  const popover = document.getElementById('allotment-combobox-dropdown');
  const isHidden = popover?.classList.contains('hidden');

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (isHidden) {
      openAllotmentCombobox();
      return;
    }
    if (allotmentFilteredItems.length > 0) {
      allotmentHighlightedIndex = (allotmentHighlightedIndex + 1) % allotmentFilteredItems.length;
      updateAllotmentHighlight();
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (isHidden) {
      openAllotmentCombobox();
      return;
    }
    if (allotmentFilteredItems.length > 0) {
      allotmentHighlightedIndex = (allotmentHighlightedIndex - 1 + allotmentFilteredItems.length) % allotmentFilteredItems.length;
      updateAllotmentHighlight();
    }
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (!isHidden && allotmentFilteredItems.length > 0) {
      const targetIdx = allotmentHighlightedIndex >= 0 ? allotmentHighlightedIndex : 0;
      const targetIpo = allotmentFilteredItems[targetIdx];
      if (targetIpo) selectAllotmentIpo(targetIpo.id);
    }
  } else if (e.key === 'Escape') {
    closeAllotmentCombobox();
  }
}

function updateAllotmentHighlight() {
  document.querySelectorAll('.allotment-option-item').forEach((el, idx) => {
    if (idx === allotmentHighlightedIndex) {
      el.classList.add('bg-blue-100', 'dark:bg-blue-900/60', 'ring-1', 'ring-blue-500');
      el.scrollIntoView({ block: 'nearest' });
    } else {
      el.classList.remove('bg-blue-100', 'dark:bg-blue-900/60', 'ring-1', 'ring-blue-500');
    }
  });
}

function selectAllotmentIpo(ipoId) {
  const ipo = allotmentIposList.find(i => i.id === ipoId);
  if (!ipo) return;

  selectedAllotmentIpo = ipo;

  // Set input display and hidden inputs
  const input = document.getElementById('allotment-combobox-input');
  if (input) input.value = ipo.company_name;

  const clearBtn = document.getElementById('allotment-combobox-clear');
  if (clearBtn) clearBtn.classList.remove('hidden');

  const ipoIdInput = document.getElementById('allotment-selected-ipo-id');
  if (ipoIdInput) ipoIdInput.value = ipo.id;

  const compSelect = document.getElementById('allotment-company-select');
  if (compSelect) compSelect.value = ipo.registrar_code || ipo.company_name;

  closeAllotmentCombobox();

  // Populate Selected IPO Card
  const card = document.getElementById('allotment-selected-card');
  const nameEl = document.getElementById('allotment-selected-name');
  const subEl = document.getElementById('allotment-selected-sub');
  const badgesEl = document.getElementById('allotment-selected-badges');
  const regEl = document.getElementById('allotment-selected-registrar');
  const dateEl = document.getElementById('allotment-selected-date');

  if (nameEl) nameEl.textContent = ipo.company_name;
  if (subEl) subEl.textContent = `${ipo.symbol} • ${ipo.ipo_type || 'Mainboard'}`;
  if (regEl) regEl.textContent = formatRegistrarDisplay(ipo.registrar_name);
  const formattedAllotDate = ipo.allotment_date ? formatAllotmentDate(ipo.allotment_date) : 'To be announced';
  if (dateEl) dateEl.textContent = formattedAllotDate;

  if (badgesEl) {
    const stClean = (ipo.status || '').toUpperCase();
    const isLive = stClean === 'LIVE';
    badgesEl.innerHTML = `
      <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded ${isLive ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700'} uppercase">
        ${stClean}
      </span>
      <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
        ${formatRegistrarDisplay(ipo.registrar_name)}
      </span>
    `;
  }
  if (card) card.classList.remove('hidden');

  // Clear previous results
  const resultBox = document.getElementById('allotment-result');
  if (resultBox) {
    resultBox.classList.add('hidden');
    resultBox.innerHTML = '';
  }

  // Routing Checks:
  const banner = document.getElementById('allotment-before-date-banner');
  const bannerText = document.getElementById('allotment-before-date-text');
  const inlineForm = document.getElementById('allotment-inline-form');
  const extCard = document.getElementById('allotment-external-card');

  const todayStr = new Date().toISOString().slice(0, 10);
  const isBeforeAllotmentDate = Boolean(ipo.allotment_date && ipo.allotment_date > todayStr);

  if (isBeforeAllotmentDate) {
    // 4c: Before allotment date: show notice, disable lookup
    if (bannerText) bannerText.textContent = `Allotment expected on ${formattedAllotDate}`;
    if (banner) banner.classList.remove('hidden');
    if (inlineForm) inlineForm.classList.add('hidden');
    if (extCard) extCard.classList.add('hidden');
    refreshLucideIcons();
    return;
  } else {
    if (banner) banner.classList.add('hidden');
  }

  // Route based on registrar support:
  if (ipo.supported_inline) {
    // 4a: Link Intime inline live query
    if (inlineForm) inlineForm.classList.remove('hidden');
    if (extCard) extCard.classList.add('hidden');
  } else {
    // 4b: External Registrar routing
    if (inlineForm) inlineForm.classList.add('hidden');
    if (extCard) extCard.classList.remove('hidden');

    const regName = formatRegistrarDisplay(ipo.registrar_name);
    const extTitle = document.getElementById('external-registrar-title');
    if (extTitle) extTitle.textContent = `This IPO's registrar is ${regName}`;

    const extBtn = document.getElementById('allotment-external-btn');
    const extBtnText = document.getElementById('allotment-external-btn-text');
    const regUrl = ipo.registrar_allotment_url ||
                   DEFAULT_REGISTRAR_EXTERNAL_URLS[(ipo.registrar_name || '').toUpperCase()] ||
                   'https://www.chittorgarh.com/report/ipo-allotment-status-check-date-process/23/';

    if (extBtn) extBtn.href = regUrl;
    if (extBtnText) extBtnText.textContent = `Open ${regName} Allotment Page ↗`;
  }

  refreshLucideIcons();
}

function updateIdentifierLabel() {
  const queryType = document.querySelector('input[name="query_type"]:checked')?.value || 'PAN';
  const label = document.getElementById('identifier-label');
  const input = document.getElementById('query-value');
  if (!label || !input) return;

  if (queryType === 'PAN') {
    label.textContent = 'PAN Number';
    input.placeholder = 'e.g. ABCDE1234F';
    input.style.textTransform = 'uppercase';
  } else if (queryType === 'APPLICATION_NO') {
    label.textContent = 'Application Number';
    input.placeholder = 'e.g. 12345678';
    input.style.textTransform = 'none';
  } else if (queryType === 'DP_CLIENT_ID') {
    label.textContent = 'DP / Client ID';
    input.placeholder = 'e.g. 1208160012345678 or IN30012612345678';
    input.style.textTransform = 'uppercase';
  }
}

async function handleAllotmentSubmit(e) {
  e.preventDefault();
  if (!selectedAllotmentIpo) {
    alert('Please select an IPO issue from the search box.');
    return;
  }

  const todayStr = new Date().toISOString().slice(0, 10);
  if (selectedAllotmentIpo.allotment_date && selectedAllotmentIpo.allotment_date > todayStr) {
    alert(`Allotment is expected on ${formatAllotmentDate(selectedAllotmentIpo.allotment_date)}. Live check is not yet active.`);
    return;
  }

  const companyId = document.getElementById('allotment-company-select')?.value || selectedAllotmentIpo.company_name;
  const queryType = document.querySelector('input[name="query_type"]:checked')?.value || 'PAN';
  const queryVal = (document.getElementById('query-value')?.value || '').trim();

  if (!queryVal || queryVal.length < 3) {
    alert('Please enter a valid identifier.');
    return;
  }

  const btn = document.getElementById('allotment-submit-btn');
  const spinner = document.getElementById('allotment-spinner');
  const resultBox = document.getElementById('allotment-result');

  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('hidden');

  try {
    const res = await fetch('/api/v1/allotment/linkintime/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: companyId, query_type: queryType, query_value: queryVal })
    });
    const data = await res.json();
    if (resultBox) resultBox.classList.remove('hidden');

    if (!res.ok || data.status === 'ERROR' || data.success === false) {
      const errorMsg = data.message || 'Registrar unavailable';
      if (resultBox) {
        resultBox.innerHTML = `
          <div class="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-xs font-semibold flex items-center gap-2">
            <i data-lucide="alert-circle" class="w-4 h-4 shrink-0 text-rose-500"></i>
            <span>${errorMsg}</span>
          </div>
        `;
      }
      refreshLucideIcons();
      return;
    }

    const isAllotted = data.status === 'ALLOTTED';
    const isNotFound = data.status === 'NOT_FOUND';

    if (resultBox) {
      resultBox.innerHTML = `
        <div class="p-4 rounded-xl ${isAllotted ? 'bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800' : isNotFound ? 'bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800' : 'bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800'} space-y-2.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-slate-800 dark:text-slate-200">${data.company_name || selectedAllotmentIpo.company_name}</span>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded ${isAllotted ? 'bg-emerald-600 text-white' : isNotFound ? 'bg-amber-500 text-white' : 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300'}">${data.status}</span>
          </div>
          <p class="text-xs font-semibold text-slate-900 dark:text-white leading-relaxed">${data.message}</p>
          <div class="grid grid-cols-2 gap-2 text-[11px] bg-white dark:bg-[#121826] p-2.5 rounded-lg border border-slate-100 dark:border-slate-800">
            <div><span class="text-slate-400 block text-[10px]">Applied</span> ${data.shares_applied ?? '—'} sh</div>
            <div><span class="text-slate-400 block text-[10px]">Allotted</span> <strong class="${isAllotted ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-700 dark:text-slate-300'}">${data.shares_allotted ?? 0} sh</strong></div>
          </div>
        </div>
      `;
    }
    refreshLucideIcons();
  } catch (err) {
    if (resultBox) {
      resultBox.classList.remove('hidden');
      resultBox.innerHTML = `
        <div class="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-xs font-semibold flex items-center gap-2">
          <i data-lucide="alert-circle" class="w-4 h-4 shrink-0 text-rose-500"></i>
          <span>Registrar unavailable</span>
        </div>
      `;
    }
    refreshLucideIcons();
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add('hidden');
  }
}

// Close combobox dropdown when clicking outside
document.addEventListener('click', function(e) {
  const wrapper = document.getElementById('allotment-combobox-wrapper');
  if (wrapper && !wrapper.contains(e.target)) {
    closeAllotmentCombobox();
  }
});


// ==================== SCORING METHODOLOGY DYNAMIC RENDERING & CALCULATOR ====================
let scoringRulesData = null;

async function loadScoringMethodology() {
  if (!scoringRulesData) {
    try {
      const res = await fetch('/api/v1/scoring/rules');
      if (res.ok) {
        scoringRulesData = await res.json();
        renderScoringRulesUI(scoringRulesData);
      }
    } catch (err) {
      console.error('Error fetching scoring rules:', err);
    }
  }

  try {
    const trRes = await fetch('/api/v1/scoring/track-record');
    if (trRes.ok) {
      const trData = await trRes.json();
      renderTrackRecordUI(trData);
    }
  } catch (err) {
    console.error('Error fetching track record:', err);
  }

  runCalculator();
  refreshLucideIcons();
}

function renderScoringRulesUI(config) {
  if (!config || !config.pillars) return;

  const verBadge = document.getElementById('formula-version-badge');
  if (verBadge && config.version && config.updated_at) {
    verBadge.textContent = `Scoring v${config.version} · updated ${config.updated_at}`;
  }
  const chgText = document.getElementById('formula-changelog-text');
  if (chgText && config.changelog) {
    chgText.textContent = `Changelog: ${config.changelog}`;
  }

  const container = document.getElementById('dynamic-pillars-container');
  if (!container) return;

  const p = config.pillars;

  // 1. GMP HTML
  const gmpMainRows = (p.gmp.mainboard || []).map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-mono font-medium">${r.condition}</td>
      <td class="py-1.5 pr-2 text-slate-500 dark:text-slate-400">${r.tier}</td>
      <td class="py-1.5 text-right font-mono font-bold text-emerald-700 dark:text-emerald-300">${r.points}</td>
    </tr>
  `).join('');

  const gmpSmeRows = (p.gmp.sme || []).map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-mono font-medium">${r.condition}</td>
      <td class="py-1.5 pr-2 text-slate-500 dark:text-slate-400">${r.tier}</td>
      <td class="py-1.5 text-right font-mono font-bold text-emerald-700 dark:text-emerald-300">${r.points}</td>
    </tr>
  `).join('');

  // 2. Subscription HTML
  const subComp = p.subscription.components || [];
  const qibComp = subComp.find(c => c.name.includes('QIB')) || { rules: [] };
  const retailComp = subComp.find(c => c.name.includes('Retail')) || { rules: [] };
  const totalComp = subComp.find(c => c.name.includes('Total')) || { rules: [] };

  const qibRows = qibComp.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition} <span class="text-[11px] text-slate-400 block">${r.note || ''}</span></td>
      <td class="py-1.5 text-right font-mono font-bold text-blue-700 dark:text-blue-300 whitespace-nowrap">${r.points}</td>
    </tr>
  `).join('');

  const retailRows = retailComp.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition}</td>
      <td class="py-1.5 text-right font-mono font-bold text-blue-700 dark:text-blue-300">${r.points}</td>
    </tr>
  `).join('');

  const totalRows = totalComp.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition}</td>
      <td class="py-1.5 text-right font-mono font-bold text-blue-700 dark:text-blue-300">${r.points}</td>
    </tr>
  `).join('');

  // 3. Valuation HTML
  const valComp = p.valuation.components || [];
  const peRel = valComp.find(c => c.name.includes('Primary')) || { rules: [] };
  const peAbs = valComp.find(c => c.name.includes('Absolute')) || { rules: [] };
  const ronwComp = valComp.find(c => c.name.includes('RoNW')) || { rules: [] };

  const peRelRows = peRel.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition} <span class="text-[11px] text-slate-400 block">${r.note || ''}</span></td>
      <td class="py-1.5 text-right font-mono font-bold text-purple-700 dark:text-purple-300">${r.points}</td>
    </tr>
  `).join('');

  const peAbsRows = peAbs.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition}</td>
      <td class="py-1.5 text-right font-mono font-bold text-purple-700 dark:text-purple-300">${r.points}</td>
    </tr>
  `).join('');

  const ronwRows = ronwComp.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition}</td>
      <td class="py-1.5 text-right font-mono font-bold text-purple-700 dark:text-purple-300">${r.points}</td>
    </tr>
  `).join('');

  // 4. Structure HTML
  const structComp = p.structure.components || [];
  const freshComp = structComp.find(c => c.name.includes('Fresh')) || { rules: [] };
  const sizeComp = structComp.find(c => c.name.includes('Size')) || { mainboard_rules: [], sme_rules: [] };

  const freshRows = freshComp.rules.map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">${r.condition}</td>
      <td class="py-1.5 text-right font-mono font-bold text-amber-700 dark:text-amber-300">${r.points}</td>
    </tr>
  `).join('');

  const mbSizeRows = (sizeComp.mainboard_rules || []).map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">Mainboard ${r.condition}</td>
      <td class="py-1.5 pr-2 text-slate-500 dark:text-slate-400">${r.tier}</td>
      <td class="py-1.5 text-right font-mono font-bold text-amber-700 dark:text-amber-300">${r.points}</td>
    </tr>
  `).join('');

  const smeSizeRows = (sizeComp.sme_rules || []).map(r => `
    <tr>
      <td class="py-1.5 pr-2 font-medium">SME ${r.condition}</td>
      <td class="py-1.5 pr-2 text-slate-500 dark:text-slate-400">${r.tier}</td>
      <td class="py-1.5 text-right font-mono font-bold text-amber-700 dark:text-amber-300">${r.points}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <!-- Pillar 1: GMP -->
    <div class="p-5 rounded-2xl bg-emerald-50/40 dark:bg-emerald-950/20 border border-emerald-200/80 dark:border-emerald-800/40 space-y-3.5 flex flex-col justify-between">
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <h4 class="font-bold text-slate-900 dark:text-white text-sm flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> 1. Grey Market Premium (GMP)
          </h4>
          <span class="text-xs font-extrabold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-900/60 px-2.5 py-0.5 rounded">Max 35 Pts</span>
        </div>
        <p class="text-xs text-slate-600 dark:text-slate-300 leading-snug">
          ${p.gmp.description || 'Evaluates unlisted OTC demand, listing cushion, and buyer sentiment.'}
        </p>
        <div class="p-2 rounded bg-emerald-100/70 dark:bg-emerald-900/40 text-[11px] text-emerald-900 dark:text-emerald-200">
          ⚡ <strong>Linear Interpolation:</strong> Values between cutoff thresholds are continuously interpolated.
        </div>
        <div>
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">Mainboard Thresholds</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-emerald-200 dark:border-emerald-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">GMP %</th><th class="py-1 pr-2">Tier</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-emerald-100 dark:divide-slate-800/60">${gmpMainRows}</tbody>
          </table>
        </div>
        <div class="pt-1">
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">SME Thresholds</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-emerald-200 dark:border-emerald-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">GMP %</th><th class="py-1 pr-2">Tier</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-emerald-100 dark:divide-slate-800/60">${gmpSmeRows}</tbody>
          </table>
        </div>
      </div>
      <div class="pt-2 border-t border-emerald-200/60 dark:border-emerald-900/40 text-[11px] text-slate-500 dark:text-slate-400 space-y-0.5">
        <div>• <strong>No GMP yet:</strong> 15.0 pts (pre-bidding neutral baseline)</div>
        <div>• <strong>Subject-to-Sauda:</strong> Up to +1.5 bonus points for firm buyer commitment</div>
      </div>
    </div>

    <!-- Pillar 2: Subscription Demand -->
    <div class="p-5 rounded-2xl bg-blue-50/40 dark:bg-blue-950/20 border border-blue-200/80 dark:border-blue-800/40 space-y-3.5 flex flex-col justify-between">
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <h4 class="font-bold text-slate-900 dark:text-white text-sm flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span> 2. Subscription Demand
          </h4>
          <span class="text-xs font-extrabold text-blue-700 dark:text-blue-300 bg-blue-100 dark:bg-blue-900/60 px-2.5 py-0.5 rounded">Max 30 Pts</span>
        </div>
        <p class="text-xs text-slate-600 dark:text-slate-300 leading-snug">
          ${p.subscription.description || 'Evaluates institutional (QIB), retail, and aggregate bidding demand.'}
        </p>
        <div class="p-2 rounded bg-blue-100/70 dark:bg-blue-900/40 text-[11px] text-blue-900 dark:text-blue-200">
          ⚡ <strong>Linear Interpolation:</strong> QIB points are linearly interpolated between 0x–1x, 1x–5x, and 5x–Target (30x Mainboard / 60x SME).
        </div>
        <div>
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">QIB Demand (Max 16 Pts)</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-blue-200 dark:border-blue-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">Multiple Band</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-blue-100 dark:divide-slate-800/60">${qibRows}</tbody>
          </table>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
          <div>
            <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">Retail (Max 6 Pts)</span>
            <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
              <tbody class="divide-y divide-blue-100 dark:divide-slate-800/60">${retailRows}</tbody>
            </table>
          </div>
          <div>
            <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">Total (Max 8 Pts)</span>
            <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
              <tbody class="divide-y divide-blue-100 dark:divide-slate-800/60">${totalRows}</tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="pt-2 border-t border-blue-200/60 dark:border-blue-900/40 text-[11px] text-slate-500 dark:text-slate-400">
        • Early Day 1/2 QIB bidding is evaluated neutrally (5.0 pts) without premature closing penalties.
      </div>
    </div>

    <!-- Pillar 3: Valuation & Financials -->
    <div class="p-5 rounded-2xl bg-purple-50/40 dark:bg-purple-950/20 border border-purple-200/80 dark:border-purple-800/40 space-y-3.5 flex flex-col justify-between">
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <h4 class="font-bold text-slate-900 dark:text-white text-sm flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span> 3. Valuation &amp; Financials
          </h4>
          <span class="text-xs font-extrabold text-purple-700 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/60 px-2.5 py-0.5 rounded">Max 20 Pts</span>
        </div>
        <p class="text-xs text-slate-600 dark:text-slate-300 leading-snug">
          ${p.valuation.description || 'Compares valuation multiples against sector peers and capital efficiency (RoNW).'}
        </p>
        <div>
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">P/E vs Industry Peers (Max 12 Pts)</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-purple-200 dark:border-purple-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">Relative Valuation Condition</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-purple-100 dark:divide-slate-800/60">${peRelRows}</tbody>
          </table>
        </div>
        <div class="pt-1">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-bold text-slate-800 dark:text-slate-200">Absolute P/E Fallback</span>
            <span class="text-[10px] text-purple-700 dark:text-purple-300 font-semibold">(If Industry P/E Unavailable)</span>
          </div>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <tbody class="divide-y divide-purple-100 dark:divide-slate-800/60">${peAbsRows}</tbody>
          </table>
        </div>
        <div class="pt-1">
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">RoNW Capital Efficiency (Max 8 Pts)</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <tbody class="divide-y divide-purple-100 dark:divide-slate-800/60">${ronwRows}</tbody>
          </table>
        </div>
      </div>
      <div class="pt-2 border-t border-purple-200/60 dark:border-purple-900/40 text-[11px] text-slate-500 dark:text-slate-400">
        • Loss-making companies receive 2.0 pts in P/E and 0.0 pts in RoNW to account for profitability risks.
      </div>
    </div>

    <!-- Pillar 4: Structure & Fresh Issue -->
    <div class="p-5 rounded-2xl bg-amber-50/40 dark:bg-amber-950/20 border border-amber-200/80 dark:border-amber-800/40 space-y-3.5 flex flex-col justify-between">
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <h4 class="font-bold text-slate-900 dark:text-white text-sm flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span> 4. Structure &amp; Fresh Issue
          </h4>
          <span class="text-xs font-extrabold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/60 px-2.5 py-0.5 rounded">Max 15 Pts</span>
        </div>
        <p class="text-xs text-slate-600 dark:text-slate-300 leading-snug">
          ${p.structure.description || 'Reviews primary fresh growth capital vs secondary OFS exit and issue liquidity sizing.'}
        </p>
        <div>
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">Fresh Issue Proceeds Ratio (Max 10 Pts)</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-amber-200 dark:border-amber-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">Allocation Condition</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-amber-100 dark:divide-slate-800/60">${freshRows}</tbody>
          </table>
        </div>
        <div class="pt-1">
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200 block mb-1">Issue Size &amp; Liquidity Comfort (Max 5 Pts)</span>
          <table class="w-full text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead><tr class="border-b border-amber-200 dark:border-amber-900/60 text-left font-bold text-slate-900 dark:text-white"><th class="py-1 pr-2">Issue Size Band</th><th class="py-1 pr-2">Tier</th><th class="py-1 text-right">Pts</th></tr></thead>
            <tbody class="divide-y divide-amber-100 dark:divide-slate-800/60">
              ${mbSizeRows}
              ${smeSizeRows}
            </tbody>
          </table>
        </div>
      </div>
      <div class="pt-2 border-t border-amber-200/60 dark:border-amber-900/40 text-[11px] text-slate-500 dark:text-slate-400">
        • ₹100–300 Cr Mainboard size is classified as Mid-Sized Issue (4.0 pts) with adequate market liquidity.
      </div>
    </div>
  `;

  // Recommendation Cutoffs
  const cutoffsContainer = document.getElementById('dynamic-cutoffs-container');
  if (cutoffsContainer && config.recommendation_cutoffs) {
    cutoffsContainer.innerHTML = config.recommendation_cutoffs.map(c => `
      <div class="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 space-y-1.5">
        <div class="flex items-center justify-between">
          <span class="text-xs font-extrabold ${c.tier === 'STRONG APPLY' ? 'text-emerald-700 dark:text-emerald-300' : c.tier === 'APPLY' ? 'text-blue-700 dark:text-blue-300' : c.tier === 'NEUTRAL' ? 'text-amber-700 dark:text-amber-300' : 'text-rose-700 dark:text-rose-300'}">${c.tier}</span>
          <span class="text-xs font-mono font-bold text-slate-800 dark:text-slate-200">${c.min_score === 0 ? '< 45 pts' : '≥ ' + c.min_score + ' pts'}</span>
        </div>
        <p class="text-[11px] text-slate-600 dark:text-slate-400 leading-snug">
          ${c.description}
        </p>
      </div>
    `).join('');
  }

  // Not Yet Included Factors
  const notIncContainer = document.getElementById('dynamic-not-included-container');
  if (notIncContainer && config.notes && config.notes.not_yet_included) {
    notIncContainer.innerHTML = config.notes.not_yet_included.map(item => `
      <div class="p-3 rounded-lg bg-slate-50/80 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 space-y-1">
        <strong class="text-slate-800 dark:text-slate-200 flex items-center gap-1.5 font-bold">
          <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> ${item.factor || item}
        </strong>
        <p class="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
          ${item.description || 'Under research for inclusion in future scoring formula release.'}
        </p>
      </div>
    `).join('');
  }
}

function renderTrackRecordUI(trData) {
  const container = document.getElementById('dynamic-track-record-container');
  if (!container || !trData || !trData.tiers) return;

  const tiers = [
    { key: 'STRONG APPLY', label: 'Strong Apply', color: 'emerald' },
    { key: 'APPLY', label: 'Apply', color: 'blue' },
    { key: 'NEUTRAL', label: 'Neutral', color: 'amber' },
    { key: 'AVOID', label: 'Avoid', color: 'rose' }
  ];

  container.innerHTML = tiers.map(t => {
    const item = trData.tiers[t.key] || { count: 0, status: 'not enough data', display: 'Not enough data (<20 IPOs)' };
    const isOk = item.status === 'ok';

    return `
      <div class="p-4 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs font-extrabold text-${t.color}-700 dark:text-${t.color}-300 uppercase">${t.label}</span>
          <span class="text-[11px] font-mono text-slate-500 dark:text-slate-400">${item.count} listed</span>
        </div>
        <div>
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Avg Listing Gain</span>
          <span class="text-base font-extrabold font-mono ${isOk ? `text-${t.color}-600 dark:text-${t.color}-400` : 'text-slate-400 dark:text-slate-500'}">
            ${item.display || (isOk ? item.avg_gain_pct + '%' : 'Not enough data (<20 IPOs)')}
          </span>
        </div>
        <p class="text-[10px] text-slate-500 dark:text-slate-400">
          ${isOk ? 'Statistically validated based on ≥20 listings' : 'Threshold < 20 IPOs to prevent sample distortion'}
        </p>
      </div>
    `;
  }).join('');
}

// ── Score Calculator logic ──
let calcDebounceTimer = null;

function runCalculator() {
  clearTimeout(calcDebounceTimer);
  calcDebounceTimer = setTimeout(async () => {
    const payload = {
      ipo_type: document.getElementById('calc-type')?.value || 'MAINBOARD',
      gmp_pct: parseFloat(document.getElementById('calc-gmp')?.value) || 0,
      qib_multiple: parseFloat(document.getElementById('calc-qib')?.value) || 0,
      retail_multiple: parseFloat(document.getElementById('calc-retail')?.value) || 0,
      total_multiple: parseFloat(document.getElementById('calc-total')?.value) || 0,
      pe_ratio: parseFloat(document.getElementById('calc-pe')?.value) || null,
      industry_pe: parseFloat(document.getElementById('calc-ind-pe')?.value) || null,
      ronw: parseFloat(document.getElementById('calc-ronw')?.value) || null,
      fresh_issue_pct: parseFloat(document.getElementById('calc-fresh-pct')?.value) || 50,
      issue_size_crores: parseFloat(document.getElementById('calc-size')?.value) || 500
    };

    try {
      const res = await fetch('/api/v1/scoring/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const result = await res.json();
        const scoreEl = document.getElementById('calc-res-score');
        if (scoreEl) scoreEl.textContent = result.composite_score;

        const badgeEl = document.getElementById('calc-res-badge');
        if (badgeEl) {
          badgeEl.textContent = result.recommendation;
          const recClean = result.recommendation.replace(' ', '_');
          badgeEl.className = `mt-1 inline-block px-3 py-1 rounded-lg font-extrabold text-xs badge-${recClean}`;
        }

        document.getElementById('calc-res-gmp').textContent = result.gmp_score;
        document.getElementById('calc-res-sub').textContent = result.subscription_score;
        document.getElementById('calc-res-val').textContent = result.valuation_score;
        document.getElementById('calc-res-struct').textContent = result.structure_score;

        document.getElementById('calc-bar-gmp').style.width = `${(result.gmp_score / 100) * 100}%`;
        document.getElementById('calc-bar-sub').style.width = `${(result.subscription_score / 100) * 100}%`;
        document.getElementById('calc-bar-val').style.width = `${(result.valuation_score / 100) * 100}%`;
        document.getElementById('calc-bar-struct').style.width = `${(result.structure_score / 100) * 100}%`;
      }
    } catch (err) {
      console.warn('Calculator calculation error:', err);
    }
  }, 150);
}

function resetCalculatorForm() {
  if (document.getElementById('calc-type')) document.getElementById('calc-type').value = 'MAINBOARD';
  if (document.getElementById('calc-gmp')) document.getElementById('calc-gmp').value = '25';
  if (document.getElementById('calc-qib')) document.getElementById('calc-qib').value = '12';
  if (document.getElementById('calc-retail')) document.getElementById('calc-retail').value = '6';
  if (document.getElementById('calc-total')) document.getElementById('calc-total').value = '18';
  if (document.getElementById('calc-pe')) document.getElementById('calc-pe').value = '24';
  if (document.getElementById('calc-ind-pe')) document.getElementById('calc-ind-pe').value = '30';
  if (document.getElementById('calc-ronw')) document.getElementById('calc-ronw').value = '18';
  if (document.getElementById('calc-fresh-pct')) document.getElementById('calc-fresh-pct').value = '75';
  if (document.getElementById('calc-size')) document.getElementById('calc-size').value = '650';
  runCalculator();
}
