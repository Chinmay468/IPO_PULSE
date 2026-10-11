// ==================== SHARED APPLICATION STATE & CONSTANTS ====================
let allIpos = [];
let currentPortfolioHoldings = [];
let previousHoldingsPrices = {};
let currentActiveTab = 'portfolio';
let liveSyncInterval = null;
let liveSyncEnabled = true;
let globalAdvisoryData = null;
let expandedRowSymbol = null;
let currentSortCol = 'current_value';
let currentSortAsc = false;
let aiChatHistory = [];
let activeHoldingCharts = {};
let holdingChartRange = {};
let holdingChartType = {};
let portfolioSnapshotsChart = null;
let pnlByStockChart = null;
let ipoGmpChart = null;
let ipoSubChart = null;
let currentMFHoldings = [];
let currentMFSortCol = 'current_value';
let currentMFSortAsc = false;
let mfCategoryChart = null;
let mfAmcChart = null;
let mfHistoryLineChart = null;
let activeMFSchemeId = null;
const API = '/api/v1/portfolio';

// ==================== THEME MANAGEMENT ====================
function initTheme() {
  const urlParams = new URLSearchParams(window.location.search);
  const queryParam = urlParams.get('theme');
  const saved = localStorage.getItem('ipo_theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  let isDark = true;
  if (queryParam) {
    isDark = (queryParam === 'dark');
  } else if (saved) {
    isDark = (saved === 'dark');
  } else {
    isDark = true;
  }

  if (isDark) {
    document.documentElement.classList.add('dark');
    document.documentElement.classList.remove('light');
  } else {
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  }
  refreshLucideIcons();
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark');
  document.documentElement.classList.toggle('light', !isDark);
  localStorage.setItem('ipo_theme', isDark ? 'dark' : 'light');
  refreshLucideIcons();
  if (typeof portfolioSnapshotsChart !== 'undefined' && portfolioSnapshotsChart) renderPortfolioSnapshotsChart();
  if (typeof pnlByStockChart !== 'undefined' && pnlByStockChart) renderPnlByStockChart(currentPortfolioHoldings);
  if (typeof expandedRowSymbol !== 'undefined' && expandedRowSymbol && typeof renderHoldingChart === 'function') renderHoldingChart(expandedRowSymbol);
}

function refreshLucideIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// ==================== FORMATTERS & HELPERS ====================
function fmtINR(val) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  const isNeg = n < 0;
  const formatted = Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (isNeg ? '-₹' : '₹') + formatted;
}

function fmtPct(val) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  const sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(2) + '%';
}

function pnlColorClass(val) {
  if (val == null || isNaN(val)) return 'text-slate-500';
  return Number(val) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400';
}

function pnlChipHTML(val, isDay = false) {
  if (val == null || isNaN(val)) return '—';
  const n = Number(val);
  const isPos = n >= 0;
  const arrow = isPos ? '▲' : '▼';
  const bgClass = isPos 
    ? 'bg-[#DCFCE7] dark:bg-[#064E3B] text-[#16A34A] dark:text-[#34D399]' 
    : 'bg-[#FEE2E2] dark:bg-[#7F1D1D] text-[#DC2626] dark:text-[#F87171]';
  return `<span class="inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${bgClass} tabular-nums">${arrow} ${fmtPct(n)}</span>`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function fmtMFDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch (e) {
    return dateStr;
  }
}
