#!/usr/bin/env python3
"""Mirror 606mag.com from the Wayback Machine (latest genuine capture per page).

Storage is content-addressed: every payload is saved once as _blobs/<DIGEST>, where
DIGEST is the CDX digest (base32 SHA-1 of the original bytes). Each download is
verified against it, so we know we got exactly the capture we asked for.

For each identity in the manifest, candidates are tried best-first. A candidate is
rejected if its content is a defacement, parking page, homepage fallback, or a
PHP/MySQL error page; the next-latest capture is then tried. Soft problems (PHP
warnings inside otherwise real pages) are accepted only if nothing cleaner exists.

archive.org throttles the /web/ replay path by refusing TCP connections, so
connection errors back off and retry in later passes instead of failing.

With --history REGEX, every genuine version of the matching identities is also
fetched (after the normal resolution) and listed under index[id]['history'], so
pages whose content rotated (the homepage) keep their full past.

Usage: fetch.py MANIFEST OUTDIR [--passes N] [--only REGEX] [--limit N]
                [--migrate OLD_INDEX OLD_DIR] [--history REGEX]
"""
import base64, hashlib, json, os, random, re, socket, sys, time
import urllib.error, urllib.request

man_path, outdir = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
def opt(name, default=None, cast=str, n=1):
    if name not in args:
        return default
    i = args.index(name)
    return cast(args[i + 1]) if n == 1 else args[i + 1:i + 1 + n]
passes = opt('--passes', 8, int)
limit = opt('--limit', None, int)
only = opt('--only')
migrate = opt('--migrate', None, n=2)
history = opt('--history')

manifest = json.load(open(man_path))
if only:
    rx = re.compile(only)
    manifest = [m for m in manifest if rx.search(m['id'])]
if limit:
    manifest = manifest[:limit]

blobs = os.path.join(outdir, '_blobs')
os.makedirs(blobs, exist_ok=True)
index_path = os.path.join(outdir, '_index.json')
index = json.load(open(index_path)) if os.path.exists(index_path) else {}

def b32sha1(data):
    return base64.b32encode(hashlib.sha1(data).digest()).decode()

def blob_path(digest):
    return os.path.join(blobs, digest)

def have_blob(digest):
    return os.path.exists(blob_path(digest))

def save_index():
    tmp = index_path + '.tmp'
    json.dump(index, open(tmp, 'w'))
    os.replace(tmp, index_path)

# ---- one-time import of files fetched by the v1 downloader ----
if migrate:
    old_index, old_dir = migrate
    n = 0
    for v in json.load(open(old_index)).values():
        p = os.path.join(old_dir, v.get('path', ''))
        if v.get('ok') and os.path.isfile(p):
            data = open(p, 'rb').read()
            d = b32sha1(data)
            if not have_blob(d):
                open(blob_path(d), 'wb').write(data)
                n += 1
    print('migrated %d blobs from v1 download' % n, flush=True)

# ---- content validation ----
HARD = [
    (re.compile(rb'hacked\s+by', re.I), 'defacement'),
    (re.compile(rb'is almost here!|has not yet uploaded their website', re.I), 'parking page'),
]
SOFT = [
    (re.compile(rb'<b>(Warning|Fatal error|Parse error|Notice)</b>:', re.I), 'php error'),
    (re.compile(rb'mysql_\w+\(\)|supplied argument is not a valid MySQL|'
                rb'Can\'t connect to (local )?MySQL|Access denied for user|'
                rb'Too many connections|Unknown database|Lost connection to MySQL', re.I),
     'mysql error'),
]
LISTING = re.compile(rb'<title>Index of /', re.I)

def problems(ident, kind, data):
    """Return (hard_reasons, soft_reasons)."""
    if kind != 'html':
        return [], []
    hard = [why for rx, why in HARD if rx.search(data)]
    soft = [why for rx, why in SOFT if rx.search(data)]
    # a directory listing is legitimate for a directory URL, not for a page
    if LISTING.search(data) and not ident.split('?')[0].endswith('/'):
        hard.append('directory listing instead of page')
    if ident == '/' and LISTING.search(data):
        hard.append('directory listing instead of splash')
    return hard, soft

# ---- network ----
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120 Safari/537.36')
DEAD = {400, 403, 404, 410, 451}
state = {'delay': 1.0, 'throttle': 0}

class Throttled(Exception):
    pass

def download(cand):
    """Fetch a capture's exact bytes, verified against its digest. Returns bytes,
    or None if the capture is gone / Wayback served something else."""
    url = 'https://web.archive.org/web/%sid_/%s' % (cand['ts'], cand['url'])
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            state['delay'] = max(0.8, state['delay'] * 0.95)
            if b32sha1(data) != cand['digest']:
                return None                     # redirected to a different capture
            return data
        except urllib.error.HTTPError as e:
            if e.code in DEAD:
                return None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
            pass
        state['throttle'] += 1
        state['delay'] = min(45.0, max(2.0, state['delay'] * 2.0))
        time.sleep(state['delay'] + random.random() * 3)
    raise Throttled()

def up_to_date(m):
    """True if this identity's stored resolution still matches its candidate list
    (a rebuilt manifest can add newer candidates, e.g. from Common Crawl)."""
    rec = index.get(m['id'])
    if not rec or rec.get('status') not in ('done', 'alias', 'failed'):
        return False
    real = [c for c in m['cands'] if not c.get('demoted')]
    if rec['status'] == 'alias':
        return not real
    tried = {r['ts'] for r in rec.get('skipped_newer', []) + rec.get('rejected', [])}
    if rec['status'] == 'failed':
        return all(c['ts'] in tried for c in real)
    return not real or rec.get('digest') == real[0]['digest'] or real[0]['ts'] in tried

def process(m):
    """Resolve one identity. Returns 'done', 'alias', 'failed', or 'retry'."""
    ident, kind, cands = m['id'], m['kind'], m['cands']
    if up_to_date(m):
        return index[ident]['status']
    if all(c.get('demoted') for c in cands):
        index[ident] = {'status': 'alias', 'kind': kind,
                        'note': 'only homepage/fallback captures exist'}
        return 'alias'
    rejected = []
    fallback = None
    for c in cands:
        if c.get('demoted'):
            break                                # never prefer a fallback capture
        if have_blob(c['digest']):
            data = open(blob_path(c['digest']), 'rb').read()
        elif c.get('source') in ('cc', 'server'):
            rejected.append({'ts': c['ts'], 'why': '%s record not imported' % c['source']})
            continue
        else:
            data = download(c)                   # may raise Throttled
            time.sleep(state['delay'] + random.random() * 0.4)
            if data is None:
                rejected.append({'ts': c['ts'], 'why': 'unavailable or digest mismatch'})
                continue
            open(blob_path(c['digest']), 'wb').write(data)
        hard, soft = problems(ident, kind, data)
        if hard:
            rejected.append({'ts': c['ts'], 'why': ', '.join(hard)})
            continue
        if soft:
            rejected.append({'ts': c['ts'], 'why': ', '.join(soft)})
            if fallback is None:
                fallback = (c, soft)
            continue
        index[ident] = {'status': 'done', 'kind': kind, 'ts': c['ts'], 'url': c['url'],
                        'digest': c['digest'], 'mime': c['mime'],
                        'source': c.get('source', 'wayback'), 'skipped_newer': rejected}
        return 'done'
    if fallback:
        c, soft = fallback
        index[ident] = {'status': 'done', 'kind': kind, 'ts': c['ts'], 'url': c['url'],
                        'digest': c['digest'], 'mime': c['mime'],
                        'source': c.get('source', 'wayback'),
                        'warnings': soft, 'skipped_newer': rejected}
        return 'done'
    index[ident] = {'status': 'failed', 'kind': kind, 'rejected': rejected}
    return 'failed'

t0 = time.time()
for p in range(1, passes + 1):
    todo = [m for m in manifest if not up_to_date(m)]
    if not todo:
        break
    print('=== pass %d/%d: %d identities to resolve ===' % (p, passes, len(todo)), flush=True)
    for n, m in enumerate(todo, 1):
        try:
            process(m)
        except Throttled:
            pass                                 # leave unresolved; later pass retries
        if n % 25 == 0 or n == len(todo):
            save_index()
            st = {}
            for v in index.values():
                st[v['status']] = st.get(v['status'], 0) + 1
            print('  pass%d [%4d/%4d] %s throttle=%d delay=%.1fs elapsed=%.0fmin'
                  % (p, n, len(todo), st, state['throttle'], state['delay'],
                     (time.time() - t0) / 60), flush=True)
    save_index()
    if p < passes and any(not up_to_date(m) for m in manifest):
        print('  cooling down 90s before next pass', flush=True)
        time.sleep(90)

# ---- optional: every genuine version of rotating pages ----
if history:
    rx = re.compile(history)
    targets = [m for m in manifest if rx.search(m['id']) and m['id'] in index]
    for p in range(1, 4):
        pending = 0
        for m in targets:
            versions = []
            for c in m['cands']:
                if c.get('demoted'):
                    continue
                if not have_blob(c['digest']):
                    try:
                        data = download(c)
                        time.sleep(state['delay'] + random.random() * 0.4)
                    except Throttled:
                        pending += 1
                        continue
                    if data is None:
                        continue
                    open(blob_path(c['digest']), 'wb').write(data)
                hard, soft = problems(m['id'], m['kind'],
                                      open(blob_path(c['digest']), 'rb').read())
                if not hard and not soft:
                    versions.append({'ts': c['ts'], 'url': c['url'], 'digest': c['digest']})
            index[m['id']]['history'] = sorted(versions, key=lambda v: v['ts'])
            save_index()
        print('history pass %d: %s, %d versions still throttled'
              % (p, ', '.join('%s=%d' % (m['id'], len(index[m['id']]['history']))
                              for m in targets), pending), flush=True)
        if not pending:
            break
        time.sleep(90)

save_index()
st = {}
for v in index.values():
    st[v['status']] = st.get(v['status'], 0) + 1
print('FINISHED %s of %d identities in %.1f min'
      % (st, len(manifest), (time.time() - t0) / 60), flush=True)
