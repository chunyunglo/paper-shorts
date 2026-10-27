// Render the studio frame by frame in Chromium and pipe JPEGs to ffmpeg.
// With DISPLAY set (Xvfb), Chromium draws with Mesa llvmpipe; without it, SwiftShader (about 2x slower).
// node render.mjs stills 10 20.5 ...      -> stills/t_<sec>.jpg
// node render.mjs video <start> <end> out.mp4
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.vrm': 'application/octet-stream' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  fs.readFile(p, (e, d) => { if (e) { res.writeHead(404); res.end(); return; } res.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream' }); res.end(d); });
});
await new Promise((r) => server.listen(0, r));
const port = server.address().port;

// Mesa llvmpipe under Xvfb is ~2x faster than Chromium's bundled SwiftShader
const browser = process.env.DISPLAY
  ? await chromium.launch({ headless: false, args: ['--use-gl=angle', '--use-angle=gl', '--ignore-gpu-blocklist', '--no-sandbox', '--window-size=1920,1080'] })
  : await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error('[page]', m.text()); });
page.on('pageerror', (e) => console.error('[pageerror]', e.message));
await page.addInitScript(`window.QUALITY = ${process.env.QUALITY || '{"aa":true,"shadow":2048,"scale":1,"bloom":true}'};`);
await page.goto(`http://127.0.0.1:${port}/index.html`);
const tl = await page.evaluate(() => window.boot());
await page.evaluate(() => document.fonts.ready);

const [mode, ...rest] = process.argv.slice(2);
const FPS = tl.fps;
const shot = () => page.screenshot({ type: 'jpeg', quality: 90, timeout: 300000 });

if (mode === 'stills') {
  fs.mkdirSync(path.join(ROOT, 'stills'), { recursive: true });
  for (const s of rest.map(Number)) {
    // warm up physics for a second before the still
    for (let t = Math.max(0, s - 0.3); t < s; t += 1 / FPS) await page.evaluate((t) => window.renderAt(t), t);
    let a = Date.now(); await page.evaluate((t) => window.renderAt(t), s); const r = Date.now() - a;
    a = Date.now(); const img = await shot(); console.log('render', r, 'ms, shot', Date.now() - a, 'ms');
    fs.writeFileSync(path.join(ROOT, 'stills', `t_${s}.jpg`), img);
    console.log('still', s);
  }
} else {
  const start = Number(rest[0]), end = Math.min(Number(rest[1]), tl.duration), out = rest[2];
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  // warm-up so spring bones settle at chunk boundaries
  for (let t = Math.max(0, start - 1.5); t < start; t += 1 / FPS) await page.evaluate((t) => window.renderAt(t), t);
  const n0 = Math.round(start * FPS), n1 = Math.round(end * FPS);
  const t0 = Date.now();
  for (let n = n0; n < n1; n++) {
    await page.evaluate((t) => window.renderAt(t), n / FPS);
    const buf = await shot();
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    if ((n - n0) % 150 === 0) console.log(`frame ${n}/${n1} ${((Date.now() - t0) / 1000 / Math.max(1, n - n0)).toFixed(2)}s/frame`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
}
await browser.close();
server.close();
