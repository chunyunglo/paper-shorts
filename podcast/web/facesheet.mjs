// faces at several moments in one go: node facesheet.mjs out.jpg K:12 A:25.8 ... -> grid of close-ups
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const { chromium } = createRequire('/home/claude/paper-shorts/podcast/web/')('playwright');
const ROOT = path.dirname(new URL(import.meta.url).pathname);
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0])); fs.readFile(p, (e, d) => { if (e) { res.writeHead(404); res.end(); return; } res.writeHead(200, { 'content-type': p.endsWith('.html') ? 'text/html' : p.endsWith('.js') ? 'text/javascript' : 'application/octet-stream' }); res.end(d); }); });
await new Promise((r) => server.listen(0, r));
const browser = await chromium.launch({ headless: false, args: ['--use-gl=angle', '--use-angle=gl', '--ignore-gpu-blocklist', '--no-sandbox', '--window-size=1920,1080'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('pageerror', (e) => console.error('[pageerror]', e.message));
await page.addInitScript(`window.QUALITY = {"aa":true,"shadow":2048,"scale":1,"bloom":true}; window.DEBUG = ${process.env.DEBUG || '{}'};`);
await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);
await page.evaluate(() => window.boot());
await page.evaluate(() => { for (const id of ['sub','card','title','names','outro']) { const e = document.getElementById(id); if (e) e.style.display = 'none'; } });
const files = [];
for (const [i, a] of process.argv.slice(3).entries()) {
  const [k, ts, sd] = a.split(':'); const t = Number(ts);
  for (let x = t - 0.4; x <= t; x += 1 / 30) await page.evaluate((x) => window.renderAt(x), x);
  await page.evaluate(([k, sd]) => window.closeup(k, sd), [k, Number(sd || 0.35) * (k === 'A' ? -1 : 1)]);
  const f = `/tmp/fs_${i}.jpg`; fs.writeFileSync(f, await page.screenshot({ type: 'jpeg', quality: 88, clip: { x: 560, y: 60, width: 800, height: 900 } })); files.push(f);
}
await browser.close(); server.close();
execFileSync('python3', ['-c', `
import sys
from PIL import Image, ImageDraw
fs=sys.argv[2:]; labels=${JSON.stringify(process.argv.slice(3))}
ims=[Image.open(f).resize((400,450)) for f in fs]
cols=min(4,len(ims)); rows=(len(ims)+cols-1)//cols
g=Image.new('RGB',(400*cols,450*rows))
for i,im in enumerate(ims):
    ImageDraw.Draw(im).text((8,8),labels[i],fill=(255,255,0)); g.paste(im,((i%cols)*400,(i//cols)*450))
g.save(sys.argv[1])`, process.argv[2], ...files]);
