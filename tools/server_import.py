#!/usr/bin/env python3
"""Import clean files that only the DreamHost server copy has into the blob store.

Policy (decided 2026-10-09): the as-published version (Wayback / Common Crawl) wins
wherever both exist; the server copy only fills gaps. Skipped: malware, PHP source,
PHP-templated HTML/CSS, Windows Thumbs.db caches. The originals stay untouched in
server-copy/. Output uses the Common Crawl record format, marked source "server",
so build_manifest.py can merge it.

Usage: server_import.py COMPARE_JSON SERVER_ROOT ARCHIVE_DIR OUT_JSON
"""
import json, os, re, sys, time
from collections import Counter
from urllib.parse import quote

compare_path, root, arc, out_path = sys.argv[1:5]
MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.png': 'image/png',
        '.bmp': 'image/bmp', '.ico': 'image/x-icon', '.css': 'text/css', '.html': 'text/html',
        '.htm': 'text/html', '.pdf': 'application/pdf', '.doc': 'application/msword',
        '.txt': 'text/plain', '.js': 'application/javascript', '.xml': 'text/xml',
        '.swf': 'application/x-shockwave-flash', '.mov': 'video/quicktime',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
IMPORT = {'only on the server', 'same content archived under another name'}
PHP_TAG = re.compile(rb'<\?(php|=|\s)', re.I)

records, skipped = {}, Counter()
for r in json.load(open(compare_path))['files']:
    if r['compare'] not in IMPORT:
        continue
    ext = os.path.splitext(r['path'])[1].lower()
    mime = MIME.get(ext)
    if mime is None:
        skipped[ext or '(no extension)'] += 1
        continue
    data = open(os.path.join(root, r['path']), 'rb').read()
    if mime in ('text/html', 'text/css', 'application/javascript') and PHP_TAG.search(data):
        skipped['%s with PHP inside' % ext] += 1
        continue
    blob = os.path.join(arc, '_blobs', r['digest'])
    if not os.path.exists(blob):
        open(blob, 'wb').write(data)
    ts = time.strftime('%Y%m%d%H%M%S', time.strptime(r['mtime'], '%Y-%m-%d %H:%M'))
    url = 'http://www.606mag.com/' + quote(r['path'], safe="/~!$&'()*+,;=:@")
    records[url + ' ' + ts] = {'url': url, 'ts': ts, 'mime': mime, 'status': '200',
                               'digest': r['digest'], 'bytes': r['size'], 'verified': True,
                               'source': 'server'}
json.dump(records, open(out_path, 'w'), indent=1)
print('imported %d server-only files: %s' % (len(records), dict(Counter(v['mime'] for v in records.values()).most_common())))
print('skipped: %s' % dict(skipped.most_common()))
