// Checks the right-hand ad column and the Google tags in a build with test IDs (TEST) against
// the same build with the IDs empty (BASE): the column shows only at 976px and wider, sits where
// the 2004 one did, is the only thing that changes on the page, never loads Google's ad script
// on phones, excluded pages, the front door, the privacy page or the archive, and survives
// resizing. Google's servers are answered with 204, so nothing is sent to Google.
// Usage: node adcheck.mjs BASE_URL TEST_URL OUT_DIR
import fs from 'node:fs'; import path from 'node:path';
import { launch, decodePNG } from './cdp.mjs';
const [baseUrl, testUrl, out] = process.argv.slice(2);
const GOOGLE = ['googletagmanager.com', 'google-analytics.com', 'googlesyndication.com', 'doubleclick.net',
  'fundingchoicesmessages.google.com', 'adtrafficquality.google', 'googleadservices.com'];
const ELIGIBLE = ['/issues/4/', '/issues/1/john-hughes-iii/', '/issues/11/the-ad-mile/img-3/', '/issues/4/editors-note/',
  '/issues/11/the-ad-mile/', '/issues/11/', '/issues/9/brutalists/'];
const OTHER = ['/', '/privacy/', '/issues/4/to-be-a-suicidegirl/', '/issues/8/fcc/2/', '/issues/12/', '/issues/9/morning-after/', '/archive/main/id-60.html', '/archive/index.html'];
const NARROW = [320, 375, 690, 800, 975], WIDE = [976, 1024, 1280];
fs.mkdirSync(out, { recursive: true });
const browser = await launch(out);
const problems = [], notes = [];
const fail = (m) => { problems.push(m); console.log('FAIL', m); };
const adRequests = (p) => p.blocked.filter(u => u.includes('adsbygoogle.js')).length;

function compare(a, b, mask) {   // differing pixels outside the mask; extra height must be white
  const A = decodePNG(fs.readFileSync(a)), B = decodePNG(fs.readFileSync(b));
  let differ = 0, extraInk = 0;
  const H = Math.max(A.height, B.height), W = Math.max(A.width, B.width);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (mask && x >= mask[0] && x < mask[1]) continue;
    const pa = x < A.width && y < A.height ? A.data.subarray((y * A.width + x) * 4) : null;
    const pb = x < B.width && y < B.height ? B.data.subarray((y * B.width + x) * 4) : null;
    if (pa && pb) { if (Math.abs(pa[0] - pb[0]) + Math.abs(pa[1] - pb[1]) + Math.abs(pa[2] - pb[2]) > 24) differ++; }
    else { const q = pa || pb; if (q[0] < 250 || q[1] < 250 || q[2] < 250) extraInk++; }
  }
  return { differ, extraInk, heights: [A.height, B.height] };
}

for (const w of [...NARROW, ...WIDE]) {
  const pb = await browser.page(w, 900, w < 768, { block: GOOGLE });
  const pt = await browser.page(w, 900, w < 768, { block: GOOGLE });
  for (const u of [...ELIGIBLE, ...OTHER]) {
    const name = (u.replace(/^\/|\/$/g, '').replace(/[\/.]/g, '_') || 'home') + '@' + w;
    await pb.load(baseUrl + u); await pb.screenshot(path.join(out, name + '.base.png'));
    await pt.load(testUrl + u); await new Promise(r => setTimeout(r, 300)); await pt.screenshot(path.join(out, name + '.test.png'));
    const eligible = ELIGIBLE.includes(u), wide = w >= 976;
    const dom = await pt.evaluate(`(() => { const d = document.getElementById('ad_right'); if (!d) return null;
      const r = d.getBoundingClientRect(), s = getComputedStyle(d);
      const ins = [...d.querySelectorAll('ins.adsbygoogle')].map(i => { const b = i.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)]; });
      let maxRight = 0; for (const el of document.querySelectorAll('#content img, #content td:not(.ad-column) *')) { if (el.closest('.ad-column') || el.children.length && el.tagName !== 'A') continue; const b = el.getBoundingClientRect(); if (b.width && b.height && getComputedStyle(el).visibility !== 'hidden') maxRight = Math.max(maxRight, b.right); }
      return { display: s.display, rect: [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width)], ins, maxRight: Math.round(maxRight) }; })()`);
    const reqs = adRequests(pt);
    const cmp = compare(path.join(out, name + '.base.png'), path.join(out, name + '.test.png'), eligible && wide ? [796, 976] : null);
    if (!eligible || !wide) {
      if (reqs) fail(`${name}: ad script requested (${reqs})`);
      if (dom && dom.display !== 'none' && eligible) fail(`${name}: column visible below 976px`);
      if (!eligible && dom && dom.ins.length) fail(`${name}: ad units on a page without ads`);
      // the privacy page's text follows config.ts, so only its tags are checked
      if (u !== '/privacy/' && (cmp.differ || cmp.extraInk || cmp.heights[0] !== cmp.heights[1])) fail(`${name}: page changed (${JSON.stringify(cmp)})`);
    } else {
      if (reqs !== 1) fail(`${name}: ad script requested ${reqs} times`);
      if (!dom || dom.display === 'none') fail(`${name}: no visible column`);
      else {
        if (dom.rect.join() !== '796,79,179') fail(`${name}: column at ${dom.rect}`);
        if (dom.ins.length !== 2 || dom.ins.some(b => b[2] !== 160 || b[3] !== 600 || Math.abs(b[0] - 805) > 1)) fail(`${name}: units ${JSON.stringify(dom.ins)}`);
        if (dom.maxRight > 796) notes.push(`${name}: page content reaches x=${dom.maxRight}, under the column (as in 2004)`);
      }
      if (cmp.differ || cmp.extraInk) fail(`${name}: changed outside the column (${JSON.stringify(cmp)})`);
    }
    for (const t of ['base', 'test']) fs.rmSync(path.join(out, `${name}.${t}.png`));
  }
  await pb.close(); await pt.close();
  console.log('width', w, 'done');
}
// resizing: no request while narrow; one request once wide; never a second
const p = await browser.page(800, 900, false, { block: GOOGLE });
await p.load(testUrl + '/issues/1/john-hughes-iii/');
const seq = [adRequests(p)];
for (const w of [1024, 800, 1024, 1280]) { await p.resize(w); await new Promise(r => setTimeout(r, 400)); seq.push(adRequests(p)); }
const queued = await p.evaluate('(window.adsbygoogle || []).length');
if (seq.join() !== '0,1,1,1,1') fail(`resize: ad script requests by step ${seq}`);
if (queued !== 2) fail(`resize: ${queued} units queued (want 2)`);
const errors = p.console.filter(m => /TagError|availableWidth/i.test(m));
if (errors.length) fail('resize: ' + errors.join(' | '));
await browser.close();
console.log(notes.join('\n'));
console.log(problems.length ? `${problems.length} problems` : 'all checks passed');
process.exit(problems.length ? 1 : 0);
