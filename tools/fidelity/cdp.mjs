// Minimal headless-Chrome driver over the DevTools protocol (Node 22+, no dependencies):
// screenshots, network blocking, PNG decode/encode and pixel diffs. Used by compare.mjs and
// responsive.mjs to check the rebuilt pages against the 2004 originals and on small screens.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function launch(tmpRoot) {
  fs.mkdirSync(tmpRoot, { recursive: true });
  const dir = fs.mkdtempSync(path.join(tmpRoot, 'chrome-'));
  const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${dir}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--disable-gpu',
    '--force-device-scale-factor=1', '--disable-extensions', '--mute-audio', 'about:blank'],
    { stdio: ['ignore', 'ignore', 'ignore'] });
  let port, wsPath;
  for (let i = 0; i < 200 && !port; i++) {
    try { [port, wsPath] = fs.readFileSync(path.join(dir, 'DevToolsActivePort'), 'utf8').split('\n'); } catch { await sleep(100); }
  }
  if (!port) throw new Error('chrome did not start');
  const ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map(); const listeners = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
    else if (m.method) for (const l of [...listeners]) l(m);
  };
  const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const msg = { id: ++id, method, params }; if (sessionId) msg.sessionId = sessionId;
    pending.set(msg.id, { res, rej }); ws.send(JSON.stringify(msg));
  });
  return {
    /** a tab; block: hostname substrings answered with 204 (and logged in page.blocked) */
    async page(width, height = 900, mobile = false, { block = [] } = {}) {
      const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
      const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
      const s = (m, p) => send(m, p, sessionId);
      await s('Page.enable'); await s('Runtime.enable');
      await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
      if (mobile) await s('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
      const requests = [], blocked = [], console_ = [];
      listeners.push(m => {
        if (m.sessionId !== sessionId) return;
        if (m.method === 'Network.requestWillBeSent') requests.push(m.params.request.url);
        if (m.method === 'Runtime.consoleAPICalled') console_.push(m.params.args.map(a => a.value ?? a.description).join(' '));
        if (m.method === 'Fetch.requestPaused') {
          const host = new URL(m.params.request.url).hostname;
          if (block.some(b => host.includes(b))) { blocked.push(m.params.request.url); s('Fetch.fulfillRequest', { requestId: m.params.requestId, responseCode: 204, body: '' }).catch(() => {}); }
          else s('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
        }
      });
      await s('Network.enable');
      if (block.length) await s('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
      const waitEvent = (name, timeout = 20000) => new Promise(res => {
        const t = setTimeout(() => res(null), timeout);
        listeners.push(function l(m) { if (m.sessionId === sessionId && m.method === name) { clearTimeout(t); listeners.splice(listeners.indexOf(l), 1); res(m); } });
      });
      const evaluate = async expr => {
        const r = await s('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
        if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + JSON.stringify(r.exceptionDetails.exception?.description || ''));
        return r.result.value;
      };
      return {
        evaluate, requests, blocked, console: console_,
        async resize(w, h = height) { await s('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile }); await sleep(200); },
        async load(url) {
          requests.length = 0; blocked.length = 0; console_.length = 0;
          const loaded = waitEvent('Page.loadEventFired');
          await s('Page.navigate', { url });
          await loaded;
          await evaluate(`(async () => { await document.fonts.ready;
            await Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 4000); })));
          })()`);
          await sleep(150);
        },
        async screenshot(file, maxHeight = 6000) {
          const m = await s('Page.getLayoutMetrics');
          const h = Math.min(Math.ceil(m.cssContentSize.height), maxHeight);
          const w = Math.max(width, Math.ceil(m.cssContentSize.width));
          const r = await s('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
            clip: { x: 0, y: 0, width: Math.min(w, 4000), height: h, scale: 1 } });
          fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
          return { width: w, height: Math.ceil(m.cssContentSize.height) };
        },
        async close() { await send('Target.closeTarget', { targetId }); },
      };
    },
    async close() {
      try { await send('Browser.close'); } catch {}
      proc.kill(); await new Promise(r => proc.exitCode !== null ? r() : proc.once('exit', r)); await sleep(300);
      try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5 }); } catch {}
    },
  };
}

// ---- PNG (8-bit RGB/RGBA, non-interlaced: what Chrome emits) ----
export function decodePNG(buf) {
  let p = 8, w, h, ct; const idat = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p), type = buf.toString('ascii', p + 4, p + 8), data = buf.subarray(p + 8, p + 8 + len);
    if (type === 'IHDR') { w = data.readUInt32BE(0); h = data.readUInt32BE(4); ct = data[9]; if (data[8] !== 8 || data[12]) throw new Error('unsupported png'); }
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    p += 12 + len;
  }
  const bpp = ct === 6 ? 4 : ct === 2 ? 3 : (() => { throw new Error('png color type ' + ct); })();
  const raw = zlib.inflateSync(Buffer.concat(idat)), stride = w * bpp, out = Buffer.alloc(w * h * 4);
  let prev = Buffer.alloc(stride), cur = Buffer.alloc(stride);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? cur[x - bpp] : 0, b = prev[x], c = x >= bpp ? prev[x - bpp] : 0;
      let v = line[x];
      if (f === 1) v += a; else if (f === 2) v += b; else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      cur[x] = v & 255;
    }
    for (let x = 0; x < w; x++) { const o = (y * w + x) * 4; out[o] = cur[x * bpp]; out[o + 1] = cur[x * bpp + 1]; out[o + 2] = cur[x * bpp + 2]; out[o + 3] = bpp === 4 ? cur[x * bpp + 3] : 255; }
    [prev, cur] = [cur, prev];
  }
  return { width: w, height: h, data: out };
}
const CRC = (() => { const t = new Int32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c; } return t; })();
const crc32 = b => { let c = -1; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return (c ^ -1) >>> 0; };
export function encodePNG({ width, height, data }) {
  const chunk = (type, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(type), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc32(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 6;
  const raw = Buffer.alloc(height * (width * 4 + 1));
  for (let y = 0; y < height; y++) data.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

/** Pixel diff of two screenshots, ignoring columns in `mask` ([x0, x1)); optional sheet: a | b | red diff. */
export function diffPNG(aFile, bFile, sheetFile, { threshold = 24, mask = null } = {}) {
  const A = decodePNG(fs.readFileSync(aFile)), B = decodePNG(fs.readFileSync(bFile));
  const W = Math.max(A.width, B.width), H = Math.max(A.height, B.height);
  const px = (I, x, y) => (x < I.width && y < I.height) ? I.data.subarray((y * I.width + x) * 4, (y * I.width + x) * 4 + 4) : null;
  let differ = 0, firstY = -1;
  const D = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const o = (y * W + x) * 4;
    if (mask && x >= mask[0] && x < mask[1]) { D[o] = 120; D[o + 1] = 160; D[o + 2] = 255; D[o + 3] = 255; continue; }
    const a = px(A, x, y), b = px(B, x, y);
    const d = !a || !b ? 999 : Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);
    if (d > threshold) { differ++; if (firstY < 0) firstY = y; D[o] = 255; D[o + 3] = 255; }
    else { const g = a ? 200 + ((a[0] + a[1] + a[2]) / 3 | 0) * 55 / 255 : 255; D[o] = D[o + 1] = D[o + 2] = g; D[o + 3] = 255; }
  }
  if (sheetFile) {
    const gap = 8, SW = W * 3 + gap * 2, S = Buffer.alloc(SW * H * 4, 255);
    const blit = (I, ox) => { for (let y = 0; y < I.height; y++) I.data.copy(S, (y * SW + ox) * 4, y * I.width * 4, (y + 1) * I.width * 4); };
    blit(A, 0); blit(B, W + gap); blit({ width: W, height: H, data: D }, 2 * (W + gap));
    fs.writeFileSync(sheetFile, encodePNG({ width: SW, height: H, data: S }));
  }
  return { width: W, heightA: A.height, heightB: B.height, differ, ratio: differ / (W * H), firstY };
}
