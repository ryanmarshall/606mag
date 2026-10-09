#!/usr/bin/env python3
"""Fetch Common Crawl records (by byte range) into the shared blob store.

Handles both ARC (2008-2012 crawls) and WARC records, de-chunks HTTP bodies, and
verifies each body against the index digest (base32 SHA-1, same scheme as Wayback).

Usage: cc_fetch_records.py CC_INDEX_JSONL ARCHIVE_DIR OUT_JSON
"""
import base64, gzip, hashlib, json, os, re, sys, time, urllib.request

idx_path, arc, out_path = sys.argv[1:4]
blobs = os.path.join(arc, '_blobs')
os.makedirs(blobs, exist_ok=True)
recs = [json.loads(l) for l in open(idx_path) if l.startswith('{')]
results = json.load(open(out_path)) if os.path.exists(out_path) else {}

def b32sha1(b):
    return base64.b32encode(hashlib.sha1(b).digest()).decode()

def dechunk(body):
    out, i = bytearray(), 0
    while True:
        j = body.find(b'\r\n', i)
        if j < 0:
            return bytes(body)          # not actually chunked
        try:
            size = int(body[i:j].split(b';')[0].strip(), 16)
        except ValueError:
            return bytes(body)
        if size == 0:
            return bytes(out)
        out += body[j + 2:j + 2 + size]
        i = j + 2 + size + 2

def http_body(raw):
    """Slice the HTTP message using the record's declared length (records are
    followed by separator newlines), then split off the HTTP headers."""
    if raw.startswith(b'WARC/'):
        head, raw = raw.split(b'\r\n\r\n', 1)
        m = re.search(rb'(?im)^content-length:\s*(\d+)', head)
        if m:
            raw = raw[:int(m.group(1))]
    else:                                   # ARC: "URL IP DATE MIME LENGTH" line
        line, raw = raw.split(b'\n', 1)
        try:
            raw = raw[:int(line.split()[-1])]
        except ValueError:
            pass
    for sep in (b'\r\n\r\n', b'\n\n'):
        if sep in raw:
            head, body = raw.split(sep, 1)
            break
    else:
        return None, raw
    if b'transfer-encoding: chunked' in head.lower():
        body = dechunk(body)
    return head.decode('latin-1', 'replace'), body

ok = bad = 0
for r in recs:
    key = r['url'] + ' ' + r['timestamp']
    if results.get(key, {}).get('verified'):
        continue
    if r.get('status') != '200':
        continue
    start, length = int(r['offset']), int(r['length'])
    req = urllib.request.Request('https://data.commoncrawl.org/' + r['filename'],
                                 headers={'Range': 'bytes=%d-%d' % (start, start + length - 1)})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = gzip.decompress(resp.read())
            break
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    else:
        results[key] = {'url': r['url'], 'ts': r['timestamp'], 'error': 'fetch failed'}
        bad += 1
        continue
    head, body = http_body(raw)
    verified = b32sha1(body) == r.get('digest')
    # Some crawlers stored gzip-encoded bodies; keep the readable payload, verified
    # in whichever form matches the index digest.
    if body[:2] == b'\x1f\x8b' and not r['url'].endswith('.gz'):
        try:
            plain = gzip.decompress(body)
            verified = verified or b32sha1(plain) == r.get('digest')
            body = plain
        except OSError:
            pass
    d = b32sha1(body)
    open(os.path.join(blobs, d), 'wb').write(body)
    results[key] = {'url': r['url'], 'ts': r['timestamp'], 'mime': r.get('mime'),
                    'status': r.get('status'),
                    'digest': d, 'cc_digest': r.get('digest'), 'verified': verified,
                    'bytes': len(body)}
    ok += verified
    bad += not verified
    time.sleep(0.2)

json.dump(results, open(out_path, 'w'), indent=1)
print('%s: %d index records, %d with status 200; new this run: verified %d, '
      'unverified/failed %d' % (os.path.basename(idx_path), len(recs),
      sum(1 for r in recs if r.get('status') == '200'), ok, bad))
