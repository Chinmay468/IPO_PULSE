const puppeteer = require('C:/Users/VICTUS/AppData/Roaming/npm/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/VICTUS/.gemini/antigravity/brain/be37d4ce-7772-44b0-a304-b26c8849c435';

// Build standalone HTML containing Tailwind CDN and custom styles
const htmlContent = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="file:///d:/Projects/Enquirer Service/app/static/css/styles.css">
  <style>
    body { background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .card-wrapper { width: 340px; }
  </style>
</head>
<body class="p-8">

  <h2 class="text-xl font-bold text-slate-800 mb-6">IPO Card States Matrix</h2>

  <div class="grid grid-cols-2 gap-6 max-w-4xl">

    <!-- 1. LIVE IPO CARD -->
    <div id="card-live" class="card-wrapper bg-white rounded-xl border border-[#E8EAEE] shadow-sm p-4 flex flex-col justify-between space-y-3">
      <div class="space-y-2">
        <div class="flex justify-between items-start gap-1">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">TONBIMAG</span>
            <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-emerald-100 text-emerald-800 font-semibold">LIVE</span>
        </div>
        <div>
          <h4 class="font-bold text-xs text-slate-900" title="Tonbo Imaging India">Tonbo Imaging India</h4>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-50">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-STRONG_APPLY">STRONG APPLY</span>
            <span class="font-mono text-xs font-bold text-slate-800">82.4 <span class="text-[9px] text-slate-400">/100</span></span>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Price Band</div>
            <div class="font-bold text-slate-700">₹680 - ₹700</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider flex items-center justify-between">
              <span>Consensus GMP</span>
              <span class="text-[9px] px-1 py-0.2 rounded bg-slate-200 text-slate-700 font-medium">2 sources</span>
            </div>
            <div class="font-bold text-emerald-600 flex items-center gap-1">+₹500 (71.4%)</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Subscribed</div>
            <div class="font-bold text-slate-700">14.8x</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Size</div>
            <div class="font-bold text-slate-700">₹850 Cr</div>
          </div>
        </div>
      </div>
      <div class="pt-2 flex justify-between items-center text-xs">
        <span class="text-[9px] text-slate-500 font-medium">Day 2 of 3 · Closes 19 Oct</span>
        <a href="#" class="px-2.5 py-1 rounded text-xs font-bold bg-emerald-600 text-white">Apply ↗</a>
      </div>
    </div>

    <!-- 2. CLOSED IPO CARD -->
    <div id="card-closed" class="card-wrapper bg-white rounded-xl border border-[#E8EAEE] shadow-sm p-4 flex flex-col justify-between space-y-3">
      <div class="space-y-2">
        <div class="flex justify-between items-start gap-1">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">HDFIRE</span>
            <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 uppercase tracking-wider">SME</span>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-slate-100 text-slate-600 font-semibold">CLOSED</span>
        </div>
        <div>
          <h4 class="font-bold text-xs text-slate-900" title="HD Fire Protect">HD Fire Protect</h4>
          <p class="text-[9px] text-purple-600 leading-snug mt-0.5">SME: higher minimum bid, lower liquidity</p>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-50">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-200 text-slate-700">Closed</span>
            <div class="flex items-center text-xs">
              <span class="text-[10px] text-slate-400 font-medium mr-1.5">Score at close:</span>
              <span class="font-mono font-bold text-slate-800">83.2</span>
            </div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Price</div>
            <div class="font-bold text-slate-700">₹271</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider flex items-center justify-between">
              <span>Consensus GMP</span>
              <span class="text-[9px] px-1 py-0.2 rounded bg-slate-200 text-slate-700 font-medium">2 sources</span>
            </div>
            <div class="font-bold text-emerald-600">+₹81 (30.0%)</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Final Subscription</div>
            <div class="font-bold text-slate-700">131.7x</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Size</div>
            <div class="font-bold text-slate-700">₹58 Cr</div>
          </div>
        </div>
      </div>
      <div class="pt-2 flex justify-between items-center text-xs">
        <span class="text-[9px] text-slate-500 font-medium">Closed on 14 Oct</span>
        <span class="text-[10px] text-slate-400 font-medium">Closed</span>
      </div>
    </div>

    <!-- 3. LOW CONFIDENCE CARD -->
    <div id="card-low-confidence" class="card-wrapper bg-white rounded-xl border border-[#E8EAEE] shadow-sm p-4 flex flex-col justify-between space-y-3">
      <div class="space-y-2">
        <div class="flex justify-between items-start gap-1">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">ALPHA</span>
            <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-blue-100 text-blue-800 font-semibold">UPCOMING</span>
        </div>
        <div>
          <h4 class="font-bold text-xs text-slate-900" title="Alpha Therapeutics">Alpha Therapeutics Ltd</h4>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-50">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-INSUFFICIENT_DATA">Insufficient data</span>
            <span class="font-mono text-xs font-bold text-slate-400">—</span>
          </div>
          <div class="text-[9px] text-slate-500 mt-1">Missing: Grey Market Premium, P/E Ratio, RoNW, Subscription Demand</div>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Price Band</div>
            <div class="font-bold text-slate-700">TBA</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Consensus GMP</div>
            <div class="font-bold text-slate-400">N/A</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Subscribed</div>
            <div class="font-bold text-slate-400">Awaiting Bids</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Size</div>
            <div class="font-bold text-slate-700">₹450 Cr</div>
          </div>
        </div>
      </div>
      <div class="pt-2 flex justify-between items-center text-xs">
        <span class="text-[9px] text-slate-500 font-medium">Dates to be announced</span>
        <span class="text-[10px] text-slate-400 font-medium">Upcoming</span>
      </div>
    </div>

    <!-- 4. EXTREME GMP CARD -->
    <div id="card-extreme-gmp" class="card-wrapper bg-white rounded-xl border border-[#E8EAEE] shadow-sm p-4 flex flex-col justify-between space-y-3">
      <div class="space-y-2">
        <div class="flex justify-between items-start gap-1">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">SHELLZ</span>
            <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
          </div>
          <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-emerald-100 text-emerald-800 font-semibold">LIVE</span>
        </div>
        <div>
          <h4 class="font-bold text-xs text-slate-900" title="Shellz India Ltd">Shellz India Ltd</h4>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-50">
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-APPLY_VERIFY_GMP">Apply, verify GMP</span>
            <span class="font-mono text-xs font-bold text-slate-800">71.0 <span class="text-[9px] text-slate-400">/100</span></span>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Price</div>
            <div class="font-bold text-slate-700">₹175 - ₹179</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider flex items-center justify-between">
              <span>Consensus GMP</span>
              <span class="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-600 font-bold border border-amber-500/30" title="Consensus GMP is >50% of issue price">Verify before relying</span>
            </div>
            <div class="font-bold text-emerald-600">+₹110 (61.5%)</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Subscribed</div>
            <div class="font-bold text-slate-700">8.4x</div>
          </div>
          <div>
            <div class="text-[9px] text-slate-400 uppercase tracking-wider">Issue Size</div>
            <div class="font-bold text-slate-700">₹210 Cr</div>
          </div>
        </div>
      </div>
      <div class="pt-2 flex justify-between items-center text-xs">
        <span class="text-[9px] text-slate-500 font-medium">Day 2 of 3 · Closes 19 Oct</span>
        <a href="#" class="px-2.5 py-1 rounded text-xs font-bold bg-emerald-600 text-white">Apply ↗</a>
      </div>
    </div>

  </div>

</body>
</html>
`;

async function takeScreenshots() {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1000, height: 900, deviceScaleFactor: 2 });
  await page.setContent(htmlContent, { waitUntil: 'networkidle0' });

  // 1. Overview screenshot
  const overviewPath = path.join(ARTIFACT_DIR, 'card_types_overview.png');
  await page.screenshot({ path: overviewPath, fullPage: true });
  console.log('Saved: ' + overviewPath);

  // 2. Individual card screenshots
  const cards = [
    { id: '#card-live', file: 'card_live.png' },
    { id: '#card-closed', file: 'card_closed.png' },
    { id: '#card-low-confidence', file: 'card_low_confidence.png' },
    { id: '#card-extreme-gmp', file: 'card_extreme_gmp.png' },
  ];

  for (const c of cards) {
    const el = await page.$(c.id);
    if (el) {
      const targetPath = path.join(ARTIFACT_DIR, c.file);
      await el.screenshot({ path: targetPath });
      console.log('Saved: ' + targetPath);
    }
  }

  await browser.close();
  console.log('All card screenshots generated successfully.');
}

takeScreenshots().catch(err => {
  console.error('Error generating screenshots:', err);
  process.exit(1);
});
