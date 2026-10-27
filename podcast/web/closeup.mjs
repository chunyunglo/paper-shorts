// close-up still of each host's face: node closeup.mjs t out.jpg [nolook]
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
const { chromium } = createRequire('/home/claude/paper-shorts/podcast/web/')('playwright');
const ROOT = '/home/claude/paper-shorts/podcast/web';
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0])); fs.readFile(p, (e, d) => { if (e) { res.writeHead(404); res.end(); return; } res.writeHead(200, { 'content-type': p.endsWith('.html') ? 'text/html' : p.endsWith('.js') ? 'text/javascript' : 'application/octet-stream' }); res.end(d); }); });
await new Promise((r) => server.listen(0, r));
const browser = await chromium.launch({ headless: false, args: ['--use-gl=angle', '--use-angle=gl', '--ignore-gpu-blocklist', '--no-sandbox', '--window-size=1920,1080'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('pageerror', (e) => console.error('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.error('[page]', m.text(), JSON.stringify(m.location())); });
await page.addInitScript(`window.QUALITY = {"aa":true,"shadow":2048,"scale":1,"bloom":true}; window.DEBUG = ${process.argv[4] || '{}'};`);
await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);
await page.evaluate(() => window.boot());
const t = Number(process.argv[2]);
for (let x = t - 0.3; x <= t; x += 1 / 30) await page.evaluate((x) => window.renderAt(x), x);
const k = process.argv[5] || 'K'; const sd = Number(process.argv[6] || 0); await page.evaluate(([k, sd]) => window.closeup(k, sd), [k, sd]); await page.evaluate(() => { for (const id of ['sub','card','title','names','outro']) { const e = document.getElementById(id); if (e) e.style.display = 'none'; } });
fs.writeFileSync(process.argv[3], await page.screenshot({ type: 'jpeg', quality: 90 }));
await browser.close(); server.close();
