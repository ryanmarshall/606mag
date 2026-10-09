#!/usr/bin/env python3
"""Reconstruct the server's file tree from every archived Apache directory listing
(Wayback + Common Crawl) and check each listed file against what was recovered.

Files that exist in the DreamHost server copy (--server ROOT) count as recovered
even when they are not published in the rebuilt site (PHP source, Thumbs.db).

Usage: inventory.py CDX_JSON ARCHIVE_DIR OUT_JSON [CC_RECORDS_JSON ...] [--server ROOT]
"""
import html, json, os, re, sys
from collections import defaultdict
from urllib.parse import unquote, urljoin, urlparse

cdx_path, arc, out_path = sys.argv[1:4]
rest = sys.argv[4:]
server_root = rest[rest.index('--server') + 1] if '--server' in rest else None
cc_files = [a for a in rest if a != '--server' and a != server_root]
blobs = os.path.join(arc, '_blobs')
index = json.load(open(os.path.join(arc, '_index.json')))

TITLE = re.compile(rb'<title>\s*Index of\s+(/[^<]*)</title>', re.I)
ENTRY = re.compile(rb'<a href="([^"?][^"]*)">[^<]*</a>(.{0,160})', re.I | re.S)
DATE = re.compile(rb'(\d{2}-\w{3}-\d{4} \d{2}:\d{2})')
SIZE = re.compile(rb'(?:</td><td[^>]*>|\s)\s*(\d+(?:\.\d+)?[KMG]?|-)\s*(?:</td>|\s|$)')

captures = []   # (ts, url, digest)
for ts, orig, status, mime, digest, length in json.load(open(cdx_path))[1:]:
    if status == '200' and mime.startswith('text/html') and urlparse(orig).path.endswith('/'):
        captures.append((ts, orig, digest))
for f in cc_files:
    for r in json.load(open(f)).values():
        if r.get('verified') and urlparse(r['url']).path.endswith('/'):
            captures.append((r['ts'], r['url'], r['digest']))

tree = {}       # path -> {'dir': bool, 'modified': ..., 'size': ..., 'seen': [dates]}
listed_dirs = defaultdict(set)
for ts, url, digest in sorted(captures):
    p = os.path.join(blobs, digest)
    if not os.path.exists(p):
        continue
    data = open(p, 'rb').read()
    t = TITLE.search(data)
    if not t:
        continue
    base = unquote(t.group(1).decode('latin-1')).rstrip('/') + '/'
    listed_dirs[base].add(ts[:8])
    for href, tail in ENTRY.findall(data):
        name = unquote(html.unescape(href.decode('latin-1')))
        if name.startswith(('/', 'http', '../')) or name in ('./',):
            continue
        path = urljoin(base, name)
        if not path.startswith(base) or path == base:
            continue
        d, s = DATE.search(tail), SIZE.search(tail)
        e = tree.setdefault(path, {'dir': path.endswith('/'), 'seen': set()})
        e['seen'].add(ts[:8])
        if d:
            e['modified'] = d.group(1).decode()
        if s and not e['dir']:
            e['size'] = s.group(1).decode()

recovered = set()
for ident, v in index.items():
    if v.get('status') == 'done':
        recovered.add(unquote(ident.split('?')[0]))
lower = {r.lower() for r in recovered}
stand_ins = set()
report_path = os.path.join(os.path.dirname(out_path), 'report.json')
if os.path.exists(report_path):
    for op in json.load(open(report_path)).get('thumbnail_stand_ins', []):
        stand_ins.add('/' + op.replace('.thumb.png', ''))

on_server = set()
if server_root:
    for dp, _, fs in os.walk(server_root):
        for f in fs:
            on_server.add('/' + os.path.relpath(os.path.join(dp, f), server_root).replace(os.sep, '/'))
server_dirs = {p.rsplit('/', 1)[0] + '/' for p in on_server}

def status(path, e):
    if e['dir']:
        if path in listed_dirs or path in recovered:
            return 'have'
        if any(r.startswith(path) for r in recovered) or path in server_dirs:
            return 'have-part'
        return 'lost'
    if path in recovered or path.lower() in lower:
        return 'have'
    if os.path.splitext(path)[0] in stand_ins:
        return 'thumbnail'
    if path in on_server:
        return 'have (server copy only)'
    return 'lost'

out = {'listed_directories': {k: sorted(v) for k, v in sorted(listed_dirs.items())}, 'entries': {}}
counts = defaultdict(int)
for path in sorted(tree):
    e = tree[path]
    st = status(path, e)
    counts[('dir ' if e['dir'] else 'file ') + st] += 1
    out['entries'][path] = {'status': st, 'dir': e['dir'], 'modified': e.get('modified'),
                            'size': e.get('size'), 'listed_on': sorted(e['seen'])}
json.dump(out, open(out_path, 'w'), indent=1)
print('directory listings parsed: %d directories' % len(listed_dirs))
for k in sorted(counts):
    print('  %-16s %d' % (k, counts[k]))
