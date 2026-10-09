#!/usr/bin/env python3
"""Verify every internal link and image in a built static site resolves to a real file.

Checks href, src, background, CSS url() and MM_openBrWindow popup targets on every
HTML page under DIST; reports broken targets grouped by section with example pages.
External links are listed separately (their liveness is checked by check_links.py).

Usage: check_site_links.py DIST_DIR [OUT_JSON] [--relative]
"""
import html, json, os, posixpath, re, sys
from collections import defaultdict
from urllib.parse import unquote, urljoin, urlparse

args = [a for a in sys.argv[1:] if a != '--relative']
relative_only = '--relative' in sys.argv   # after relativize_dist.py: every local link must be page-relative
dist = args[0].rstrip('/')
REF = re.compile(r'''\b(href|src|background)\s*=\s*(["'])(.*?)\2''', re.I | re.S)
CSS = re.compile(r'''url\(\s*["']?([^"')]+)["']?\s*\)''', re.I)
POP = re.compile(r'''MM_openBrWindow\(\s*['"]([^'"]+)['"]''')

def exists(path):
    p = os.path.join(dist, unquote(path).lstrip('/'))
    return os.path.isfile(p) or os.path.isfile(os.path.join(p, 'index.html'))

broken = defaultdict(set)
external, pages, refs = set(), 0, 0
for dp, _, fs in os.walk(dist, followlinks=True):
    for f in fs:
        if not f.endswith('.html'):
            continue
        rel = '/' + os.path.relpath(os.path.join(dp, f), dist).replace(os.sep, '/')
        page_url = rel[:-len('index.html')] if f == 'index.html' else rel
        doc = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
        doc = re.sub(r'<!--.*?-->', '', doc, flags=re.S)
        pages += 1
        targets = [m.group(3) for m in REF.finditer(doc)] + CSS.findall(doc) + POP.findall(doc)
        for t in targets:
            t = html.unescape(t).strip()
            if not t or t.startswith(('#', 'javascript:', 'mailto:', 'data:', 'tel:')):
                continue
            refs += 1
            if relative_only and t.startswith('/') and not t.startswith('//'):
                broken['root-absolute ' + t].add(page_url)       # would miss the /606mag/ prefix
                continue
            if relative_only and posixpath.normpath(posixpath.join(posixpath.dirname(page_url), t.split('?')[0].split('#')[0])).startswith('/..'):
                broken['above the site root ' + t].add(page_url)
                continue
            u = urlparse(urljoin('http://local' + page_url, t))
            if u.netloc != 'local':
                external.add(t)
                continue
            if not exists(u.path):
                broken[u.path].add(page_url)
section = lambda p: 'archive' if p.startswith('/archive/') else 'modern'
report = {'pages': pages, 'references': refs, 'external': len(external),
          'broken': {k: sorted(v)[:5] for k, v in sorted(broken.items())}}
if len(args) > 1:
    json.dump(report, open(args[1], 'w'), indent=1)
print('pages checked: %d   references: %d   external links: %d' % (pages, refs, len(external)))
by = defaultdict(list)
for target, where in broken.items():
    by[section(next(iter(where)))].append((target, where))
for sec in ('modern', 'archive'):
    items = by.get(sec, [])
    print('%s pages: %d broken targets, referenced %d times' % (sec, len(items), sum(len(w) for _, w in items)))
    for target, where in sorted(items, key=lambda kv: -len(kv[1]))[:15]:
        print('   %-62s x%-3d e.g. %s' % (target[:62], len(where), sorted(where)[0][:60]))
sys.exit(1 if broken else 0)
