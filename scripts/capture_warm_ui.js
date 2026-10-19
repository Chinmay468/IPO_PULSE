const puppeteer = require('C:/Users/VICTUS/AppData/Roaming/npm/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/VICTUS/.gemini/antigravity/brain/be37d4ce-7772-44b0-a304-b26c8849c435';

async function capture() {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 850, deviceScaleFactor: 2 });

  // Read index.html and styles.css
  let indexHtml = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf-8');
  let stylesCss = fs.readFileSync(path.join(__dirname, '../app/static/css/styles.css'), 'utf-8');

  // Replace external css link with inline style to render offline with perfect fidelity
  indexHtml = indexHtml.replace('<link rel="stylesheet" href="/static/css/styles.css">', `<style>${stylesCss}</style>`);
  
  // Ensure light mode is active on html tag (remove 'dark' class if present for testing light mode)
  indexHtml = indexHtml.replace('<html lang="en" class="dark">', '<html lang="en">');

  await page.setContent(indexHtml, { waitUntil: 'networkidle0' });

  // Switch to IPO tab and populate sample stat counters
  await page.evaluate(() => {
    // Hide portfolio tab, show ipos tab
    const pf = document.getElementById('tab-portfolio');
    const ipos = document.getElementById('tab-ipos');
    if (pf) pf.classList.add('hidden');
    if (ipos) ipos.classList.remove('hidden');

    // Update active nav styling
    const navPf = document.getElementById('nav-portfolio');
    const navIpos = document.getElementById('nav-ipos');
    if (navPf) {
      navPf.classList.remove('text-emerald-600', 'border-emerald-500', 'font-bold');
      navPf.classList.add('text-slate-600', 'border-transparent', 'font-semibold');
    }
    if (navIpos) {
      navIpos.classList.add('text-emerald-600', 'border-emerald-500', 'font-bold');
      navIpos.classList.remove('text-slate-600', 'border-transparent', 'font-semibold');
    }

    // Populate stat counters
    const sLive = document.getElementById('stat-live');
    const sUp = document.getElementById('stat-upcoming');
    const sApp = document.getElementById('stat-apply');
    if (sLive) sLive.textContent = '5';
    if (sUp) sUp.textContent = '91';
    if (sApp) sApp.textContent = '2';

    const syncTime = document.getElementById('discovery-last-sync-time');
    if (syncTime) syncTime.textContent = '19 Oct 2026, 10:12 am (15m ago)';

    // Render sample cards into ipos-container
    const container = document.getElementById('ipos-container');
    if (container) {
      container.innerHTML = `
        <!-- Card 1: BLS Polymers -->
        <div class="bg-white rounded-xl border border-[#E8EAEE] shadow-soft p-4 flex flex-col justify-between space-y-3 hover:border-slate-300 transition">
          <div class="space-y-2">
            <div class="flex justify-between items-start gap-1">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">BLSPOLY</span>
                <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
              </div>
              <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">UPCOMING</span>
            </div>
            <div>
              <h4 class="font-bold text-xs text-slate-900" title="BLS Polymers">BLS Polymers</h4>
            </div>
            <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-bold text-slate-700">Insufficient data</span>
                <span class="text-xs text-slate-400 font-mono">-</span>
              </div>
              <p class="text-[10px] text-slate-400 mt-1">Missing: Grey Market Premium (GMP), Subscription Bidding Data</p>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">GMP</span>
                <span class="font-bold text-slate-400">N/A</span>
              </div>
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">Subscribed</span>
                <span class="font-bold text-slate-700">Awaiting Bids</span>
              </div>
            </div>
            <p class="text-[9px] text-slate-400">GMP is unofficial and can change anytime; not investment advice.</p>
            <div class="flex items-center justify-between text-[10px] text-slate-400 pt-1">
              <span>Opens in 8 days</span>
              <span>Updated 10m ago</span>
            </div>
          </div>
          <div class="pt-2 border-t border-slate-100 flex items-center justify-between">
            <button class="text-xs font-semibold text-slate-700 hover:text-slate-900 flex items-center gap-1">Analysis →</button>
            <span class="text-[11px] text-slate-400 font-medium">Upcoming</span>
          </div>
        </div>

        <!-- Card 2: Core4 Engineers (SME) -->
        <div class="bg-white rounded-xl border border-[#E8EAEE] shadow-soft p-4 flex flex-col justify-between space-y-3 hover:border-slate-300 transition">
          <div class="space-y-2">
            <div class="flex justify-between items-start gap-1">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">CORE4ENGI</span>
                <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 uppercase tracking-wider">SME</span>
              </div>
              <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">UPCOMING</span>
            </div>
            <div>
              <h4 class="font-bold text-xs text-slate-900" title="Core4 Engineers">Core4 Engineers</h4>
              <p class="text-[10px] text-purple-600 font-semibold mt-0.5">SME: higher minimum bid, lower liquidity</p>
            </div>
            <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-bold text-slate-700">Insufficient data</span>
                <span class="text-xs text-slate-400 font-mono">-</span>
              </div>
              <p class="text-[10px] text-slate-400 mt-1">Missing: Grey Market Premium (GMP), Subscription Bidding Data</p>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">GMP</span>
                <span class="font-bold text-slate-400">N/A</span>
              </div>
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">Subscribed</span>
                <span class="font-bold text-slate-700">Awaiting Bids</span>
              </div>
            </div>
            <p class="text-[9px] text-slate-400">GMP is unofficial and can change anytime; not investment advice.</p>
            <div class="flex items-center justify-between text-[10px] text-slate-400 pt-1">
              <span>Opens in 4 days</span>
              <span>Updated 7m ago</span>
            </div>
          </div>
          <div class="pt-2 border-t border-slate-100 flex items-center justify-between">
            <button class="text-xs font-semibold text-slate-700 hover:text-slate-900 flex items-center gap-1">Analysis →</button>
            <span class="text-[11px] text-slate-400 font-medium">Upcoming</span>
          </div>
        </div>

        <!-- Card 3: Jio Platforms -->
        <div class="bg-white rounded-xl border border-[#E8EAEE] shadow-soft p-4 flex flex-col justify-between space-y-3 hover:border-slate-300 transition">
          <div class="space-y-2">
            <div class="flex justify-between items-start gap-1">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">JIOPLAT</span>
                <span class="text-[9px] font-extrabold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-wider">MAINBOARD</span>
              </div>
              <span class="text-[10px] px-2 py-0.5 rounded-full shrink-0 bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">UPCOMING</span>
            </div>
            <div>
              <h4 class="font-bold text-xs text-slate-900" title="Jio Platforms">Jio Platforms</h4>
            </div>
            <div class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
              <div class="flex items-center justify-between">
                <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-APPLY">APPLY</span>
                <span class="font-mono text-xs font-bold text-slate-800">73.8 <span class="text-[9px] text-slate-400">/100</span></span>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs py-1 border-y border-slate-100 font-mono">
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">GMP <span class="text-[8px] bg-slate-100 px-1 py-0.2 rounded border border-slate-200 font-sans">2 sources</span></span>
                <span class="font-bold text-emerald-600">+₹250.5 (22.4%)</span>
              </div>
              <div>
                <span class="text-slate-400 block text-[9px] uppercase tracking-wider">Subscribed</span>
                <span class="font-bold text-slate-700">Awaiting Bids</span>
              </div>
            </div>
            <p class="text-[9px] text-slate-400">GMP is unofficial and can change anytime; not investment advice.</p>
            <div class="flex items-center justify-between text-[10px] text-slate-400 pt-1">
              <span>Opens in 2 days</span>
              <span>Updated 7m ago</span>
            </div>
          </div>
          <div class="pt-2 border-t border-slate-100 flex items-center justify-between">
            <button class="text-xs font-semibold text-slate-700 hover:text-slate-900 flex items-center gap-1">Analysis →</button>
            <button class="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold transition flex items-center gap-1">Apply ↗</button>
          </div>
        </div>
      `;
    }

    if (window.lucide) {
      window.lucide.createIcons();
    }
  });

  await new Promise(r => setTimeout(r, 800));

  const outPath = path.join(ARTIFACT_DIR, 'warm_tone_ui_preview.png');
  await page.screenshot({ path: outPath, fullPage: false });
  console.log(`Saved warm tone screenshot to: ${outPath}`);

  await browser.close();
}

capture().catch(err => {
  console.error(err);
  process.exit(1);
});
