// ==================== CHARTS & VISUALIZATIONS ====================

// Helper: Dynamic 7-day SVG Sparkline renderer
function renderSparkline(closes) {
  if (!closes || !Array.isArray(closes) || closes.length < 2) {
    return '<span class="text-slate-400 font-mono text-xs">—</span>';
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const width = 50;
  const height = 18;
  const pad = 2;
  const points = closes.map((val, idx) => {
    const x = Math.round((idx / (closes.length - 1)) * width);
    const y = Math.round(height - pad - ((val - min) / range) * (height - 2 * pad));
    return `${x},${y}`;
  });
  const pathD = 'M ' + points.join(' L ');
  const isUp = closes[closes.length - 1] >= closes[0];
  const color = isUp ? '#10B981' : '#EF4444';
  return `
    <svg class="w-10 h-4 mx-auto overflow-visible" viewBox="0 0 50 20">
      <path class="sparkline-path" d="${pathD}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  `;
}

// ── Technical & Analytics Chart Implementations (Lightweight Charts) ──
function disposeHoldingChart(symbol) {
  const item = activeHoldingCharts[symbol];
  if (item) {
    if (item.resizeObserver) {
      try { item.resizeObserver.disconnect(); } catch (e) {}
    }
    if (item.chart) {
      try { item.chart.remove(); } catch (e) {}
    }
    if (item.rsiChart) {
      try { item.rsiChart.remove(); } catch (e) {}
    }
    delete activeHoldingCharts[symbol];
  }
}

function setHoldingChartRange(symbol, range) {
  holdingChartRange[symbol] = range;
  renderHoldingChart(symbol);
}

function toggleHoldingChartType(symbol, type) {
  holdingChartType[symbol] = type;
  renderHoldingChart(symbol);
}

async function renderHoldingChart(symbol) {
  if (!symbol) return;
  disposeHoldingChart(symbol);

  const isMobile = window.innerWidth < 768;
  const mainId = isMobile ? `mholding-chart-main-${symbol}` : `holding-chart-main-${symbol}`;
  const rsiId = isMobile ? `mholding-chart-rsi-${symbol}` : `holding-chart-rsi-${symbol}`;
  const loadingId = isMobile ? `mholding-chart-loading-${symbol}` : `holding-chart-loading-${symbol}`;
  const msgId = isMobile ? `mholding-chart-msg-${symbol}` : `holding-chart-msg-${symbol}`;
  const msgTextId = isMobile ? null : `holding-chart-msg-text-${symbol}`;
  const summaryId = isMobile ? `mholding-chart-summary-${symbol}` : `holding-chart-summary-${symbol}`;

  let mainContainer = document.getElementById(mainId) || document.getElementById(`holding-chart-main-${symbol}`) || document.getElementById(`mholding-chart-main-${symbol}`);
  let rsiContainer = document.getElementById(rsiId) || document.getElementById(`holding-chart-rsi-${symbol}`) || document.getElementById(`mholding-chart-rsi-${symbol}`);
  let loadingEl = document.getElementById(loadingId) || document.getElementById(`holding-chart-loading-${symbol}`) || document.getElementById(`mholding-chart-loading-${symbol}`);
  let msgBox = document.getElementById(msgId) || document.getElementById(`holding-chart-msg-${symbol}`) || document.getElementById(`mholding-chart-msg-${symbol}`);
  let msgTextEl = (msgTextId && document.getElementById(msgTextId)) || document.getElementById(`holding-chart-msg-text-${symbol}`) || msgBox;
  let summaryEl = document.getElementById(summaryId) || document.getElementById(`holding-chart-summary-${symbol}`) || document.getElementById(`mholding-chart-summary-${symbol}`);

  if (!mainContainer) return;

  const range = holdingChartRange[symbol] || '3m';
  const chartType = holdingChartType[symbol] || 'candle';

  // Update button visual styles
  const activeRangeClasses = ['bg-indigo-600', 'text-white', 'font-bold'];
  const inactiveRangeClasses = ['text-slate-500', 'hover:text-slate-900', 'dark:hover:text-white'];

  ['1m', '3m', '6m', '1y'].forEach(r => {
    const btn = document.getElementById(`btn-range-${r}-${symbol}`);
    const mbtn = document.getElementById(`mbtn-range-${r}-${symbol}`);
    [btn, mbtn].forEach(b => {
      if (!b) return;
      if (r === range) {
        b.classList.remove(...inactiveRangeClasses);
        b.classList.add(...activeRangeClasses);
      } else {
        b.classList.remove(...activeRangeClasses);
        b.classList.add(...inactiveRangeClasses);
      }
    });
  });

  const activeTypeClasses = ['bg-white', 'dark:bg-slate-800', 'text-slate-900', 'dark:text-white', 'shadow-xs', 'font-bold'];
  const inactiveTypeClasses = ['text-slate-500', 'hover:text-slate-900', 'dark:hover:text-white'];

  ['candle', 'line'].forEach(t => {
    const btn = document.getElementById(`btn-chart-type-${t}-${symbol}`);
    const mbtn = document.getElementById(`mbtn-chart-type-${t}-${symbol}`);
    [btn, mbtn].forEach(b => {
      if (!b) return;
      if (t === chartType) {
        b.classList.remove(...inactiveTypeClasses);
        b.classList.add(...activeTypeClasses);
      } else {
        b.classList.remove(...activeTypeClasses);
        b.classList.add(...inactiveTypeClasses);
      }
    });
  });

  if (loadingEl) loadingEl.classList.remove('hidden');
  if (msgBox) msgBox.classList.add('hidden');

  if (typeof LightweightCharts === 'undefined') {
    if (loadingEl) loadingEl.classList.add('hidden');
    if (msgBox) {
      msgBox.classList.remove('hidden');
      if (msgTextEl) msgTextEl.textContent = 'TradingView chart library not loaded.';
    }
    return;
  }

  try {
    const res = await fetch(`${API}/holdings/${symbol}/history?range=${range}`, { headers: getAuthHeaders() });
    if (loadingEl) loadingEl.classList.add('hidden');

    if (!res.ok) {
      if (msgBox) {
        msgBox.classList.remove('hidden');
        if (msgTextEl) msgTextEl.textContent = `Unable to load historical candles for ${symbol} (HTTP ${res.status}).`;
      }
      return;
    }

    const data = await res.json();

    if (data.insufficient_history) {
      if (msgBox) {
        msgBox.classList.remove('hidden');
        if (msgTextEl) msgTextEl.textContent = `Insufficient trading history (< 10 trading sessions) available for ${symbol} to plot technical indicators.`;
      }
      if (summaryEl) summaryEl.textContent = `Insufficient historical trading sessions for ${symbol}.`;
      return;
    }

    if (!data.candles || data.candles.length === 0) {
      if (msgBox) {
        msgBox.classList.remove('hidden');
        if (msgTextEl) msgTextEl.textContent = `No historical trading data available for ${symbol}.`;
      }
      return;
    }

    const isDark = document.documentElement.classList.contains('dark');
    mainContainer.innerHTML = '';
    if (rsiContainer) rsiContainer.innerHTML = '';

    const chart = LightweightCharts.createChart(mainContainer, {
      layout: {
        background: { type: 'solid', color: isDark ? '#0b0f19' : '#ffffff' },
        textColor: isDark ? '#94a3b8' : '#64748b',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(51, 65, 85, 0.35)' : 'rgba(241, 245, 249, 0.8)' },
        horzLines: { color: isDark ? 'rgba(51, 65, 85, 0.35)' : 'rgba(241, 245, 249, 0.8)' },
      },
      timeScale: {
        borderColor: isDark ? '#334155' : '#e2e8f0',
        timeVisible: false,
      },
      rightPriceScale: {
        borderColor: isDark ? '#334155' : '#e2e8f0',
        scaleMargins: { top: 0.08, bottom: 0.12 },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
      },
      width: mainContainer.clientWidth || 500,
      height: isMobile ? 190 : 260,
    });

    let priceSeries;
    if (chartType === 'line') {
      priceSeries = chart.addLineSeries({
        color: '#3b82f6',
        lineWidth: 2,
        title: 'Price',
      });
      priceSeries.setData(data.candles.map(c => ({ time: c.time, value: c.close })));
    } else {
      priceSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      });
      priceSeries.setData(data.candles.map(c => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })));
    }

    // EMA 20 line
    if (data.ema20 && data.ema20.length) {
      const ema20 = chart.addLineSeries({
        color: '#f59e0b',
        lineWidth: 1.5,
        title: 'EMA 20',
      });
      ema20.setData(data.ema20.map(p => ({ time: p.time, value: p.value })));
    }

    // EMA 50 line
    if (data.ema50 && data.ema50.length) {
      const ema50 = chart.addLineSeries({
        color: '#8b5cf6',
        lineWidth: 1.5,
        title: 'EMA 50',
      });
      ema50.setData(data.ema50.map(p => ({ time: p.time, value: p.value })));
    }

    // Horizontal price lines: avg cost, stop-loss, Target 1, Target 2 with labels
    if (data.avg_cost) {
      priceSeries.createPriceLine({
        price: data.avg_cost,
        color: '#64748b',
        lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Avg Cost ₹${data.avg_cost.toFixed(2)}`,
      });
    }
    if (data.stop_loss) {
      priceSeries.createPriceLine({
        price: data.stop_loss,
        color: '#ef4444',
        lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Stop Loss ₹${data.stop_loss.toFixed(2)}`,
      });
    }
    if (data.trailing_stop) {
      priceSeries.createPriceLine({
        price: data.trailing_stop,
        color: '#f59e0b',
        lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: `Trailing SL ₹${data.trailing_stop.toFixed(2)}`,
      });
    }
    if (data.target_1) {
      priceSeries.createPriceLine({
        price: data.target_1,
        color: '#3b82f6',
        lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Target 1 (estimated) ₹${data.target_1.toFixed(2)}`,
      });
    }
    if (data.target_2) {
      priceSeries.createPriceLine({
        price: data.target_2,
        color: '#10b981',
        lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Target 2 (estimated) ₹${data.target_2.toFixed(2)}`,
      });
    }

    chart.timeScale().fitContent();

    // Small RSI(14) panel
    let rsiChart = null;
    if (rsiContainer && data.rsi14 && data.rsi14.length) {
      rsiChart = LightweightCharts.createChart(rsiContainer, {
        layout: {
          background: { type: 'solid', color: isDark ? '#0b0f19' : '#ffffff' },
          textColor: isDark ? '#94a3b8' : '#64748b',
          fontSize: 9,
        },
        grid: {
          vertLines: { color: isDark ? 'rgba(51, 65, 85, 0.35)' : 'rgba(241, 245, 249, 0.8)' },
          horzLines: { color: isDark ? 'rgba(51, 65, 85, 0.35)' : 'rgba(241, 245, 249, 0.8)' },
        },
        timeScale: {
          borderColor: isDark ? '#334155' : '#e2e8f0',
          visible: true,
        },
        rightPriceScale: {
          borderColor: isDark ? '#334155' : '#e2e8f0',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        width: rsiContainer.clientWidth || 500,
        height: isMobile ? 65 : 80,
      });

      const rsiSeries = rsiChart.addLineSeries({
        color: '#8b5cf6',
        lineWidth: 1.5,
        title: 'RSI(14)',
      });
      rsiSeries.setData(data.rsi14.map(p => ({ time: p.time, value: p.value })));

      rsiSeries.createPriceLine({
        price: 70,
        color: '#ef4444',
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: '70 Overbought',
      });
      rsiSeries.createPriceLine({
        price: 30,
        color: '#10b981',
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: '30 Oversold',
      });

      chart.timeScale().subscribeVisibleTimeRangeChange(r => {
        if (r) rsiChart.timeScale().setVisibleRange(r);
      });
      rsiChart.timeScale().subscribeVisibleTimeRangeChange(r => {
        if (r) chart.timeScale().setVisibleRange(r);
      });

      rsiChart.timeScale().fitContent();

      const latestRsi = data.rsi14[data.rsi14.length - 1]?.value;
      const rsiValEl = document.getElementById(`holding-rsi-val-${symbol}`);
      if (rsiValEl && latestRsi !== undefined) {
        rsiValEl.textContent = `Latest: ${latestRsi.toFixed(1)}`;
      }
    }

    const ro = new ResizeObserver(entries => {
      for (let entry of entries) {
        const w = entry.contentRect.width;
        if (w > 0) {
          chart.applyOptions({ width: w });
          if (rsiChart) rsiChart.applyOptions({ width: w });
        }
      }
    });
    ro.observe(mainContainer);

    activeHoldingCharts[symbol] = {
      chart,
      rsiChart,
      resizeObserver: ro,
      data,
    };

    const lastCandle = data.candles[data.candles.length - 1];
    const lastEma20 = data.ema20 && data.ema20[data.ema20.length - 1]?.value;
    const lastEma50 = data.ema50 && data.ema50[data.ema50.length - 1]?.value;
    const lastRsi = data.rsi14 && data.rsi14[data.rsi14.length - 1]?.value;
    const summaryText = `${symbol} ${range} chart: Latest Close ₹${lastCandle.close.toFixed(2)} on ${lastCandle.time}. ` +
      (lastEma20 ? `EMA20: ₹${lastEma20.toFixed(2)}, ` : '') +
      (lastEma50 ? `EMA50: ₹${lastEma50.toFixed(2)}, ` : '') +
      (lastRsi ? `RSI14: ${lastRsi.toFixed(1)}. ` : '') +
      (data.avg_cost ? `Avg Cost: ₹${data.avg_cost.toFixed(2)}, ` : '') +
      (data.stop_loss ? `Stop Loss: ₹${data.stop_loss.toFixed(2)}, ` : '') +
      (data.trailing_stop ? `Trailing SL: ₹${data.trailing_stop.toFixed(2)}, ` : '') +
      (data.target_1 ? `Target 1 (estimated): ₹${data.target_1.toFixed(2)}, ` : '') +
      (data.target_2 ? `Target 2 (estimated): ₹${data.target_2.toFixed(2)}.` : '');

    if (summaryEl) summaryEl.textContent = summaryText;
    mainContainer.setAttribute('aria-label', summaryText);
  } catch (err) {
    console.error(`Failed to load technical chart for ${symbol}:`, err);
    if (loadingEl) loadingEl.classList.add('hidden');
    if (msgBox) {
      msgBox.classList.remove('hidden');
      if (msgTextEl) msgTextEl.textContent = `Error loading chart data: ${err.message}`;
    }
  }
}

// ── Portfolio Snapshots Chart (Chart.js) ──
async function renderPortfolioSnapshotsChart() {
  if (!getAuthToken()) return;
  const collectingEl = document.getElementById('snapshots-collecting-state');
  const collectingMsg = document.getElementById('snapshots-collecting-msg');
  const chartBox = document.getElementById('snapshots-chart-container');
  const badge = document.getElementById('snapshots-count-badge');
  const summaryEl = document.getElementById('snapshots-text-summary');
  const canvas = document.getElementById('portfolio-snapshots-chart');
  if (!canvas) return;

  if (typeof Chart === 'undefined') return;

  try {
    const res = await fetch(`${API}/snapshots`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const snapshots = await res.json();

    const count = snapshots ? snapshots.length : 0;
    if (badge) badge.textContent = `${count} snapshot${count === 1 ? '' : 's'}`;

    if (!snapshots || snapshots.length < 5) {
      if (collectingEl) collectingEl.classList.remove('hidden');
      if (collectingMsg) collectingMsg.textContent = `A daily snapshot is captured after market close (16:05 IST). Recorded ${count} / 5 required sessions. Trend chart unlocks once at least 5 days of history are recorded.`;
      if (chartBox) chartBox.classList.add('hidden');
      if (summaryEl) summaryEl.textContent = `Portfolio equity tracking: ${count} of 5 historical sessions recorded.`;
      if (portfolioSnapshotsChart) {
        portfolioSnapshotsChart.destroy();
        portfolioSnapshotsChart = null;
      }
      return;
    }

    if (collectingEl) collectingEl.classList.add('hidden');
    if (chartBox) chartBox.classList.remove('hidden');

    const isDark = document.documentElement.classList.contains('dark');
    const labels = snapshots.map(s => s.date);
    const currVals = snapshots.map(s => s.current_value);
    const investedVals = snapshots.map(s => s.invested);

    if (portfolioSnapshotsChart) {
      portfolioSnapshotsChart.destroy();
    }

    const ctx = canvas.getContext('2d');
    portfolioSnapshotsChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Current Value (₹)',
            data: currVals,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: 'Invested Capital (₹)',
            data: investedVals,
            borderColor: '#64748b',
            borderDash: [4, 4],
            backgroundColor: 'transparent',
            tension: 0.1,
            borderWidth: 1.5,
            pointRadius: 2,
            pointHoverRadius: 4,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              boxWidth: 12,
              font: { size: 11 },
              color: isDark ? '#94a3b8' : '#64748b',
            }
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                return `${context.dataset.label}: ₹${Number(context.raw).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
            ticks: {
              color: isDark ? '#94a3b8' : '#64748b',
              font: { size: 10 }
            }
          },
          y: {
            grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
            ticks: {
              color: isDark ? '#94a3b8' : '#64748b',
              font: { size: 10 },
              callback: function(val) {
                return '₹' + Number(val).toLocaleString('en-IN');
              }
            }
          }
        }
      }
    });

    const latest = snapshots[snapshots.length - 1];
    const textSummary = `Portfolio value over ${snapshots.length} sessions from ${snapshots[0].date} to ${latest.date}. Current Value: ₹${latest.current_value.toLocaleString('en-IN')}, Invested: ₹${latest.invested.toLocaleString('en-IN')}, Net P&L: ₹${latest.pnl.toLocaleString('en-IN')}.`;
    if (summaryEl) summaryEl.textContent = textSummary;
    canvas.setAttribute('aria-label', textSummary);

  } catch (err) {
    console.error('Failed to load portfolio snapshots chart:', err);
  }
}

// ── P&L by Stock Horizontal Bar Chart (Chart.js) ──
function renderPnlByStockChart(holdings) {
  const emptyEl = document.getElementById('pnl-stocks-empty');
  const chartBox = document.getElementById('pnl-stocks-chart-container');
  const summaryEl = document.getElementById('pnl-stocks-text-summary');
  const canvas = document.getElementById('pnl-by-stock-chart');
  if (!canvas) return;

  if (typeof Chart === 'undefined') return;

  if (!holdings || holdings.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    if (chartBox) chartBox.classList.add('hidden');
    if (pnlByStockChart) {
      pnlByStockChart.destroy();
      pnlByStockChart = null;
    }
    return;
  }

  const sorted = [...holdings]
    .map(h => ({
      symbol: h.symbol,
      pnl: Number(h.unrealized_pnl || 0),
    }))
    .sort((a, b) => b.pnl - a.pnl);

  if (sorted.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    if (chartBox) chartBox.classList.add('hidden');
    return;
  }

  if (emptyEl) emptyEl.classList.add('hidden');
  if (chartBox) chartBox.classList.remove('hidden');

  const isDark = document.documentElement.classList.contains('dark');
  const labels = sorted.map(s => s.symbol);
  const data = sorted.map(s => s.pnl);
  const bgColors = sorted.map(s => s.pnl >= 0 ? 'rgba(16, 185, 129, 0.85)' : 'rgba(239, 68, 68, 0.85)');
  const borderColors = sorted.map(s => s.pnl >= 0 ? '#10b981' : '#ef4444');

  if (pnlByStockChart) {
    pnlByStockChart.destroy();
  }

  const ctx = canvas.getContext('2d');
  pnlByStockChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Unrealized P&L (₹)',
          data: data,
          backgroundColor: bgColors,
          borderColor: borderColors,
          borderWidth: 1,
          borderRadius: 4,
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              const val = context.raw;
              const formatted = Math.abs(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
              return `P&L: ${val >= 0 ? '+₹' : '-₹'}${formatted}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
          ticks: {
            color: isDark ? '#94a3b8' : '#64748b',
            font: { size: 10 },
            callback: function(val) {
              return (val >= 0 ? '₹' : '-₹') + Math.abs(val).toLocaleString('en-IN');
            }
          }
        },
        y: {
          grid: { display: false },
          ticks: {
            color: isDark ? '#e2e8f0' : '#1e293b',
            font: { size: 11, weight: 'bold' }
          }
        }
      }
    }
  });

  const best = sorted[0];
  const worst = sorted[sorted.length - 1];
  const summaryText = `P&L breakdown by holding: Top gainer ${best.symbol} (₹${best.pnl.toFixed(2)}), lowest performer ${worst.symbol} (₹${worst.pnl.toFixed(2)}). Total holdings: ${sorted.length}.`;
  if (summaryEl) summaryEl.textContent = summaryText;
  canvas.setAttribute('aria-label', summaryText);
}

// ── IPO Analysis Trend Charts (GMP & Subscriptions) ──
function renderIpoAnalysisCharts(detailIpo) {
  const gmpEmpty = document.getElementById('modal-gmp-empty');
  const gmpBox = document.getElementById('modal-gmp-chart-container');
  const gmpLatest = document.getElementById('modal-gmp-chart-latest');
  const gmpSummary = document.getElementById('modal-gmp-text-summary');
  const gmpCanvas = document.getElementById('modal-gmp-chart');

  const subEmpty = document.getElementById('modal-sub-empty');
  const subBox = document.getElementById('modal-sub-chart-container');
  const subLatest = document.getElementById('modal-sub-chart-latest');
  const subSummary = document.getElementById('modal-sub-text-summary');
  const subCanvas = document.getElementById('modal-sub-chart');

  const isDark = document.documentElement.classList.contains('dark');

  if (typeof Chart === 'undefined') return;

  // 1. GMP % Line Chart
  if (ipoGmpChart) {
    ipoGmpChart.destroy();
    ipoGmpChart = null;
  }

  const gmpRecords = (detailIpo.gmp_records || []).slice().sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at));
  if (!gmpRecords || gmpRecords.length === 0) {
    if (gmpEmpty) gmpEmpty.classList.remove('hidden');
    if (gmpBox) gmpBox.classList.add('hidden');
    if (gmpLatest) gmpLatest.textContent = '—';
    if (gmpSummary) gmpSummary.textContent = 'No GMP data recorded for this IPO yet.';
  } else {
    if (gmpEmpty) gmpEmpty.classList.add('hidden');
    if (gmpBox) gmpBox.classList.remove('hidden');

    const lastGmp = gmpRecords[gmpRecords.length - 1];
    if (gmpLatest) gmpLatest.textContent = `+${lastGmp.gmp_percentage}% (₹${lastGmp.gmp_amount})`;

    const labels = gmpRecords.map(r => {
      const d = new Date(r.recorded_at);
      return `${d.getDate()} ${d.toLocaleString('default', { month: 'short' })}`;
    });
    const values = gmpRecords.map(r => r.gmp_percentage);

    if (gmpCanvas) {
      const ctx = gmpCanvas.getContext('2d');
      ipoGmpChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: 'GMP (%)',
            data: values,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.12)',
            fill: true,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  const idx = ctx.dataIndex;
                  const amt = gmpRecords[idx]?.gmp_amount;
                  return `GMP: +${ctx.raw}% (₹${amt})`;
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
              ticks: { color: isDark ? '#94a3b8' : '#64748b', font: { size: 9 } }
            },
            y: {
              grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
              ticks: {
                color: isDark ? '#94a3b8' : '#64748b',
                font: { size: 9 },
                callback: v => `+${v}%`
              }
            }
          }
        }
      });

      const gmpText = `GMP percentage over ${gmpRecords.length} recorded dates. Latest GMP: +${lastGmp.gmp_percentage}% (₹${lastGmp.gmp_amount}).`;
      if (gmpSummary) gmpSummary.textContent = gmpText;
      gmpCanvas.setAttribute('aria-label', gmpText);
    }
  }

  // 2. Subscription Multiples Bar Chart
  if (ipoSubChart) {
    ipoSubChart.destroy();
    ipoSubChart = null;
  }

  const subscriptions = (detailIpo.subscriptions || []).slice().sort((a, b) => {
    if (a.day_number != null && b.day_number != null) return a.day_number - b.day_number;
    return new Date(a.recorded_at) - new Date(b.recorded_at);
  });

  if (!subscriptions || subscriptions.length === 0) {
    if (subEmpty) subEmpty.classList.remove('hidden');
    if (subBox) subBox.classList.add('hidden');
    if (subLatest) subLatest.textContent = '—';
    if (subSummary) subSummary.textContent = 'No subscription bidding data recorded yet.';
  } else {
    if (subEmpty) subEmpty.classList.add('hidden');
    if (subBox) subBox.classList.remove('hidden');

    const lastSub = subscriptions[subscriptions.length - 1];
    if (subLatest) subLatest.textContent = `${lastSub.total_multiple}x Total`;

    const labels = subscriptions.map((s, idx) => s.day_number ? `Day ${s.day_number}` : `Day ${idx + 1}`);
    const qib = subscriptions.map(s => s.qib_multiple || 0);
    const retail = subscriptions.map(s => s.retail_multiple || 0);
    const total = subscriptions.map(s => s.total_multiple || 0);

    if (subCanvas) {
      const ctx = subCanvas.getContext('2d');
      ipoSubChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'QIB',
              data: qib,
              backgroundColor: '#3b82f6',
              borderRadius: 3,
            },
            {
              label: 'Retail',
              data: retail,
              backgroundColor: '#8b5cf6',
              borderRadius: 3,
            },
            {
              label: 'Total',
              data: total,
              backgroundColor: '#10b981',
              borderRadius: 3,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                boxWidth: 8,
                font: { size: 9 },
                color: isDark ? '#94a3b8' : '#64748b',
              }
            },
            tooltip: {
              callbacks: {
                label: ctx => `${ctx.dataset.label}: ${ctx.raw}x`
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: isDark ? '#94a3b8' : '#64748b', font: { size: 9 } }
            },
            y: {
              grid: { color: isDark ? 'rgba(51, 65, 85, 0.4)' : 'rgba(241, 245, 249, 0.8)' },
              ticks: {
                color: isDark ? '#94a3b8' : '#64748b',
                font: { size: 9 },
                callback: v => `${v}x`
              }
            }
          }
        }
      });

      const subText = `Subscription demand across ${subscriptions.length} bidding days. Final overall subscription: ${lastSub.total_multiple}x (QIB: ${lastSub.qib_multiple || 0}x, Retail: ${lastSub.retail_multiple || 0}x).`;
      if (subSummary) subSummary.textContent = subText;
      subCanvas.setAttribute('aria-label', subText);
    }
  }
}

// ── Render Portfolio Allocation Donut Chart (SVG) ──
function renderAllocationDonut(holdings, totalVal) {
  const svg = document.getElementById('donut-chart-svg');
  const legend = document.getElementById('donut-legend');
  const totalEl = document.getElementById('donut-total-val');
  if (!svg || !legend) return;

  if (!holdings || holdings.length === 0 || !totalVal || totalVal <= 0) {
    svg.innerHTML = '<circle cx="21" cy="21" r="15.915" fill="none" stroke="#E2E8F0" stroke-width="6"/>';
    legend.innerHTML = '<span class="text-slate-400">No data</span>';
    if (totalEl) totalEl.textContent = '₹0.00';
    return;
  }

  if (totalEl) totalEl.textContent = fmtINR(totalVal);

  // 6 clearly distinct neutral colors: Indigo, Amber, Pink, Teal, Purple, Slate
  const colors = ['#6366F1', '#F59E0B', '#EC4899', '#14B8A6', '#8B5CF6', '#64748B'];
  let displayItems = [];
  if (holdings.length <= 6) {
    displayItems = holdings.map(h => ({
      symbol: h.symbol,
      val: Math.max(0, Number(h.current_value) || 0)
    }));
  } else {
    const sorted = [...holdings].sort((a, b) => (Number(b.current_value) || 0) - (Number(a.current_value) || 0));
    const top5 = sorted.slice(0, 5);
    const othersVal = sorted.slice(5).reduce((sum, h) => sum + Math.max(0, Number(h.current_value) || 0), 0);
    displayItems = top5.map(h => ({
      symbol: h.symbol,
      val: Math.max(0, Number(h.current_value) || 0)
    }));
    if (othersVal > 0) {
      displayItems.push({ symbol: `Others (${sorted.length - 5})`, val: othersVal });
    }
  }

  let accumulatedOffset = 0;
  let svgCircles = '';
  let legendItems = '';

  displayItems.forEach((item, idx) => {
    const color = colors[idx];
    const pct = Math.max(0, (item.val / totalVal) * 100);
    const dashArray = `${pct.toFixed(1)} ${ (100 - pct).toFixed(1) }`;
    const dashOffset = (100 - accumulatedOffset);
    accumulatedOffset += pct;

    svgCircles += `
      <circle cx="21" cy="21" r="15.915" fill="none" stroke="${color}" stroke-width="5"
              stroke-dasharray="${dashArray}" stroke-dashoffset="${dashOffset}"/>
    `;

    legendItems += `
      <div class="flex items-center justify-between gap-1.5 py-0.5">
        <div class="flex items-center gap-1.5 min-w-0">
          <span class="w-2.5 h-2.5 rounded-full shrink-0 shadow-2xs" style="background: ${color}"></span>
          <span class="truncate font-semibold text-slate-800 dark:text-slate-200 text-[11px]">${item.symbol}</span>
        </div>
        <span class="font-mono font-bold text-slate-700 dark:text-slate-300 shrink-0 text-[11px] tabular-nums">${pct.toFixed(1)}%</span>
      </div>
    `;
  });

  svg.innerHTML = svgCircles;
  legend.innerHTML = legendItems;
}
