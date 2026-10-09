#!/usr/bin/env python3
"""Compare a recovered server folder (already malware-scanned) with what the web
archives gave us, by content digest (base32 SHA-1, the Wayback/Common Crawl scheme).

Usage: server_compare.py SCAN_JSON MANIFEST ARCHIVE_DIR OUT_JSON
"""
import json, os, sys
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

scan_path, man_path, arc, out_path = sys.argv[1:5]
scan = json.load(open(scan_path))
manifest = json.load(open(man_path))
index = json.load(open(os.path.join(arc, '_index.json')))
blobs = set(os.listdir(os.path.join(arc, '_blobs')))

# every digest the archives ever had for each path, plus the one the rebuild uses
by_path = defaultdict(set)
for m in manifest:
    path = unquote(urlparse(m['id']).path)
    for c in m['cands']:
        by_path[path].add(c['digest'])
chosen = {unquote(urlparse(k).path): v['digest'] for k, v in index.items()
          if v.get('status') == 'done' and '?' not in k}
digest_paths = defaultdict(set)
for path, ds in by_path.items():
    for d in ds:
        digest_paths[d].add(path)

FALSE_POSITIVE = {'PHP code inside non-PHP file'}
rows, counts, kinds = [], Counter(), defaultdict(Counter)
for r in scan:
    real_flags = [x for x in r['strong'] if x not in FALSE_POSITIVE and not
                  (x == 'defacement marker' and r['path'].endswith('ChangeLog.txt'))]
    if real_flags:
        status = 'malware (excluded)'
    else:
        path = '/' + r['path']
        dirpath = path.rsplit('/', 1)[0] + '/'
        if path.endswith(('/index.html', '/index.php', '/index.htm')) and dirpath in by_path:
            alias = dirpath
        else:
            alias = None
        known = by_path.get(path, set()) | (by_path.get(alias, set()) if alias else set())
        if r['digest'] == chosen.get(path) or (alias and r['digest'] == chosen.get(alias)):
            status = 'identical to the rebuilt copy'
        elif r['digest'] in known:
            status = 'identical to an archived version'
        elif known:
            status = 'archived, but different content'
        elif r['digest'] in blobs or r['digest'] in digest_paths:
            status = 'same content archived under another name'
        else:
            status = 'only on the server'
    ext = os.path.splitext(r['path'])[1].lower() or '(none)'
    counts[status] += 1
    kinds[status][ext] += 1
    rows.append(dict(r, compare=status))

server_paths = {'/' + r['path'] for r in scan}
server_dirs = {p.rsplit('/', 1)[0] + '/' for p in server_paths}
archived_only = sorted(p for p in chosen if p not in server_paths and p not in server_dirs
                       and not p.endswith('/'))
json.dump({'files': rows, 'archived_not_on_server': archived_only}, open(out_path, 'w'), indent=1)
print('server files: %d' % len(scan))
for k, v in counts.most_common():
    print('  %-42s %5d   %s' % (k, v, ', '.join('%s %d' % kv for kv in kinds[k].most_common(5))))
print('recovered from archives but not on the server: %d' % len(archived_only))
