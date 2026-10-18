const puppeteer = require('C:/Users/VICTUS/AppData/Roaming/npm/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/VICTUS/.gemini/antigravity/brain/be37d4ce-7772-44b0-a304-b26c8849c435';

const htmlContent = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>IPO Analysis Modal - Tonbo Imaging India</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="file:///d:/Projects/Enquirer Service/app/static/css/styles.css">
  <style>
    body { background-color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
    .badge-APPLY_VERIFY_GMP { background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
  </style>
</head>
<body class="p-6">

  <!-- ==================== SCORE BREAKDOWN MODAL (IPO) ==================== -->
  <div id="score-modal-container" class="bg-white rounded-2xl max-w-xl w-full shadow-2xl border border-[#E8EAEE] flex flex-col overflow-hidden">
    
    <!-- Modal Header -->
    <div class="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/70">
      <div>
        <div class="flex items-center gap-2 flex-wrap">
          <h3 class="font-bold text-sm text-slate-900">Tonbo Imaging India</h3>
          <span class="text-[10px] bg-slate-100 text-slate-700 font-mono font-bold px-1.5 py-0.5 rounded">TONBIMAG</span>
          <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
        </div>
        <p class="text-[11px] text-slate-400 mt-0.5">Source: Chittorgarh · updated 2h ago · Algorithmic Analysis</p>
      </div>
      <span class="px-2.5 py-1 rounded-lg font-bold text-xs badge-APPLY_VERIFY_GMP">Apply, verify GMP</span>
    </div>

    <div class="p-5 space-y-4 text-xs">
      <!-- Composite Score -->
      <div class="p-3.5 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-between">
        <div>
          <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Composite Score</p>
          <div class="flex items-baseline gap-1 mt-0.5">
            <span class="text-2xl font-bold font-mono text-slate-900">61.0</span>
            <span class="text-slate-400 text-xs">/ 100</span>
          </div>
        </div>
        <div class="text-right">
          <span class="text-[10px] font-bold text-amber-600 block uppercase tracking-wider">Extreme GMP Rule</span>
          <span class="text-[11px] text-slate-500">GMP > 50% of Issue Price</span>
        </div>
      </div>

      <!-- Pillar Contribution Breakdown Stacked Bar -->
      <div class="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-2">
        <div class="flex justify-between items-center text-[11px] font-semibold text-slate-600">
          <span>Pillar Contribution Breakdown</span>
          <span class="font-mono font-bold text-slate-900">61.0 / 100</span>
        </div>
        <div class="h-3 w-full bg-slate-200 rounded-full overflow-hidden flex shadow-inner">
          <div class="bg-emerald-500 h-full" style="width: 28%" title="GMP (28.0/35)"></div>
          <div class="bg-blue-500 h-full" style="width: 16%" title="Subscription (16.0/30)"></div>
          <div class="bg-purple-500 h-full" style="width: 10%" title="Valuation (10.0/20)"></div>
          <div class="bg-amber-500 h-full" style="width: 7%" title="Structure (7.0/15)"></div>
        </div>
        <div class="flex justify-between text-[10px] text-slate-500 pt-0.5 font-mono">
          <span>GMP: <strong class="text-emerald-600">28.0</strong>/35</span>
          <span>Sub: <strong class="text-blue-600">16.0</strong>/30</span>
          <span>Val: <strong class="text-purple-600">10.0</strong>/20</span>
          <span>Struct: <strong class="text-amber-600">7.0</strong>/15</span>
        </div>
      </div>

      <!-- Financial Stats -->
      <div class="pt-2 border-t border-slate-100 space-y-2">
        <h5 class="font-bold text-slate-800">Financial Stats</h5>
        <div class="grid grid-cols-4 gap-2 text-[11px]">
          <div class="p-2 bg-slate-50 rounded-lg">
            <span class="text-slate-400 block">Rev Growth</span>
            <strong class="font-mono text-slate-900">Declined 89.9%</strong>
          </div>
          <div class="p-2 bg-slate-50 rounded-lg">
            <span class="text-slate-400 block">PAT Growth</span>
            <strong class="font-mono text-rose-600">Swung to a loss</strong>
          </div>
          <div class="p-2 bg-slate-50 rounded-lg">
            <span class="text-slate-400 block">P/E Ratio</span>
            <strong class="font-mono text-slate-700">Not Meaningful</strong>
          </div>
          <div class="p-2 bg-slate-50 rounded-lg">
            <span class="text-slate-400 block">Debt/Eq</span>
            <strong class="font-mono text-slate-900">—</strong>
          </div>
        </div>
      </div>

      <!-- Positive & Risk Factors -->
      <div class="space-y-2">
        <ul class="p-3 bg-emerald-50/70 text-emerald-800 rounded-lg text-[11px] space-y-1">
          <li>• Strong Grey Market Premium of 71.4% (capped at 28.0 strong tier due to extreme GMP threshold).</li>
          <li>• Healthy overall subscription of 5.6x across categories.</li>
        </ul>
        <ul class="p-3 bg-rose-50/70 text-rose-800 rounded-lg text-[11px] space-y-1">
          <li>• Loss-making operations (P/E is not meaningful).</li>
          <li>• Profitability: PAT swung to a loss.</li>
          <li>• Negative Profit Margin: Net PAT Margin of -47.5% reflects loss-making operations.</li>
          <li>• Predominantly Offer for Sale (OFS); proceeds go to selling shareholders rather than company.</li>
        </ul>
      </div>

      <!-- Market Dynamics & Demand Trends -->
      <div class="pt-2 border-t border-slate-100 space-y-3">
        <h5 class="font-bold text-slate-800 text-xs">Market Dynamics & Demand Trends</h5>
        <div class="grid grid-cols-2 gap-3">
          
          <!-- GMP Trend Chart -->
          <div class="p-3 bg-slate-50 rounded-xl space-y-2 flex flex-col justify-between">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">GMP Trend (% Gain)</span>
              <span class="text-[10px] font-mono text-emerald-600 font-bold">+71.4% (₹50)</span>
            </div>
            <div class="relative w-full h-36 flex items-center justify-center">
              <canvas id="modal-gmp-chart"></canvas>
            </div>
            <div class="text-[9px] text-slate-400 text-center">Consensus median across 2 sources (IST timestamps)</div>
          </div>

          <!-- Subscription Demand Chart -->
          <div class="p-3 bg-slate-50 rounded-xl space-y-2 flex flex-col justify-between">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">Subscription Demand</span>
              <div class="flex items-center gap-1.5">
                <div class="inline-flex items-center p-0.5 rounded-md bg-slate-200/80 text-[9px] font-semibold">
                  <button class="px-1.5 py-0.5 rounded bg-white text-slate-900 shadow-xs">Daily</button>
                  <button class="px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-900">Intraday</button>
                </div>
                <span class="text-[10px] font-mono text-blue-600 font-bold">5.6x Total</span>
              </div>
            </div>
            <div class="relative w-full h-36 flex items-center justify-center">
              <canvas id="modal-sub-chart"></canvas>
            </div>
            <div class="text-[9px] text-slate-400 text-center">Grouped by bidding day (Last snapshot per day)</div>
          </div>

        </div>
      </div>

    </div>
  </div>

  <script>
    // Render GMP Chart
    const gmpCtx = document.getElementById('modal-gmp-chart').getContext('2d');
    new Chart(gmpCtx, {
      type: 'line',
      data: {
        labels: ['16 Oct 13:54'],
        datasets: [
          {
            label: 'Investorgain',
            data: [71.43],
            borderColor: '#f59e0b',
            backgroundColor: '#f59e0b',
            fill: false,
            pointRadius: 5,
            pointHoverRadius: 7
          },
          {
            label: 'IPOWatch',
            data: [71.43],
            borderColor: '#6366f1',
            backgroundColor: '#6366f1',
            fill: false,
            pointRadius: 5,
            pointHoverRadius: 7
          },
          {
            label: 'Consensus Median',
            data: [71.43],
            borderColor: '#10b981',
            backgroundColor: '#10b981',
            fill: false,
            borderWidth: 2.5,
            pointRadius: 6,
            pointHoverRadius: 8
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
            labels: { boxWidth: 7, font: { size: 8 } }
          }
        },
        scales: {
          x: { ticks: { font: { size: 8 } } },
          y: {
            min: 50,
            max: 90,
            ticks: { font: { size: 8 }, callback: v => '+' + v + '%' }
          }
        }
      }
    });

    // Render Subscription Chart
    const subCtx = document.getElementById('modal-sub-chart').getContext('2d');
    new Chart(subCtx, {
      type: 'bar',
      data: {
        labels: ['Day 1', 'Day 2', 'Day 3 (close)'],
        datasets: [
          {
            label: 'QIB',
            data: [0.1, 0.4, 0.0],
            backgroundColor: '#3b82f6',
            borderRadius: 3
          },
          {
            label: 'NII',
            data: [0.3, 0.9, 0.0],
            backgroundColor: '#f59e0b',
            borderRadius: 3
          },
          {
            label: 'Retail',
            data: [0.8, 2.1, 0.0],
            backgroundColor: '#8b5cf6',
            borderRadius: 3
          },
          {
            label: 'Total',
            data: [0.6, 1.8, 5.6],
            backgroundColor: '#10b981',
            borderRadius: 3
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
            labels: { boxWidth: 7, font: { size: 8 } }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 8 } } },
          y: { ticks: { font: { size: 8 }, callback: v => v + 'x' } }
        }
      }
    });
  </script>
</body>
</html>
`;

async function main() {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 800, height: 950, deviceScaleFactor: 2 });
  await page.setContent(htmlContent, { waitUntil: 'networkidle0' });

  // Wait 1s for Chart.js rendering
  await new Promise(r => setTimeout(r, 1000));

  const el = await page.$('#score-modal-container');
  const outPath = path.join(ARTIFACT_DIR, 'tonbo_analysis_modal.png');
  await el.screenshot({ path: outPath });
  console.log('Saved screenshot to:', outPath);

  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
