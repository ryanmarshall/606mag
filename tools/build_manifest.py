#!/usr/bin/env python3
"""Build the download manifest from the Wayback CDX index.

Each distinct page/file ("identity") gets an ordered list of candidate captures,
best first. Policy: the LATEST GENUINE capture of that page.

  * Only captures before the Aug 2015 defacement (cutoff below); after that the
    domain shows a "Hacked By" page and then a DreamHost parking page.
  * Query URLs are normalized: PHPSESSID dropped, "amp;" key prefixes fixed,
    params sorted, so session-ID duplicates collapse into one identity.
  * For non-HTML identities (images, css, pdf), HTML captures are ignored.
  * For HTML pages other than the homepage, captures whose content digest matches
    any homepage capture are demoted: once the database died (~2010) every
    main.php?id=N simply served the homepage.
  * Digests shared by 3+ different identities are demoted (generic fallbacks).
  * Demoted captures stay at the end of the list as a last resort, so no identity
    ever loses all its candidates.

The fetcher validates content and walks down the list until one passes.

With --cc, verified Common Crawl captures (already in the blob store, see
cc_fetch_records.py) are merged in as extra candidates, marked source "cc". The
same flag takes the DreamHost server-copy records (server_import.py, source
"server"); those are used only for pages no archive captured, so the as-published
version always wins.

Usage: build_manifest.py CDX_JSON OUT_JSON [--cc RECORDS_JSON ...]
"""
import json, re, sys
from collections import defaultdict, Counter
from urllib.parse import urlparse, parse_qsl, urlencode

CDX, OUT = sys.argv[1], sys.argv[2]
CC_FILES = sys.argv[sys.argv.index('--cc') + 1:] if '--cc' in sys.argv else []
CUTOFF = '20150731999999'          # last genuine capture is 2015-07-27

rows = json.load(open(CDX))[1:]    # timestamp, original, statuscode, mimetype, digest, length

SKIP_PATH = re.compile(r'^/(phpad/|robots\.txt$|favicon\.(ico|gif)$)')

def identity(url):
    """Normalized path+query, without host."""
    p = urlparse(url)
    path = p.path or '/'
    pairs = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        while k.startswith('amp;'):
            k = k[4:]
        if k.lower() == 'phpsessid' or k == '':
            continue
        pairs.append((k, v))
    pairs.sort()
    q = urlencode(pairs)
    return path + ('?' + q if q else '')

def is_listing_sort(url):
    """Apache autoindex sort links: ?C=N;O=D"""
    return bool(re.match(r'^[CO]=[A-Z](;|$)', urlparse(url).query))

HOME_IDS = {'/', '/main.php', '/index.php', '/index.php?leave=1'}

caps = defaultdict(list)
for ts, orig, status, mime, digest, length in rows:
    if status != '200' or ts > CUTOFF or mime == 'warc/revisit':
        continue
    p = urlparse(orig)
    if SKIP_PATH.match(p.path) or is_listing_sort(orig):
        continue
    try:
        ln = int(length)
    except ValueError:
        ln = 0
    caps[identity(orig)].append({'ts': ts, 'url': orig, 'digest': digest,
                                 'mime': mime, 'len': ln})

# Common Crawl captures: only verified 200s whose bytes are already in the blob store
n_cc = 0
for f in CC_FILES:
    for r in json.load(open(f)).values():
        if not r.get('verified') or r.get('status', '200') != '200' or r['ts'] > CUTOFF:
            continue
        p = urlparse(r['url'])
        if SKIP_PATH.match(p.path) or is_listing_sort(r['url']):
            continue
        caps[identity(r['url'])].append({'ts': r['ts'], 'url': r['url'], 'digest': r['digest'],
                                         'mime': (r.get('mime') or 'unk').lower(),
                                         'len': r.get('bytes', 0), 'source': r.get('source', 'cc')})
        n_cc += 1

# as published wins: server-copy files only fill pages that no archive captured (an
# archived HTML error page at an image/stylesheet address is not a published version)
MEDIA_EXT = re.compile(r'\.(jpe?g|gif|png|bmp|ico|swf|pdf|doc|css|js)$', re.I)
for ident, cs in caps.items():
    media = MEDIA_EXT.search(ident.split('?')[0])
    published_real = [c for c in cs if c.get('source') != 'server'
                      and not (media and c['mime'].startswith('text/html'))]
    if published_real:
        caps[ident] = [c for c in cs if c.get('source') != 'server']

home_digests = {c['digest'] for i in HOME_IDS for c in caps.get(i, [])}
owners = defaultdict(set)
for ident, cs in caps.items():
    for c in cs:
        owners[c['digest']].add(ident)

manifest = []
stats = Counter()
for ident, cs in sorted(caps.items()):
    non_html = [c for c in cs if not c['mime'].startswith('text/html')]
    if non_html:
        cs = non_html
    kind = 'html' if cs[0]['mime'].startswith('text/html') else 'asset'

    # one candidate per distinct digest, keeping that digest's latest capture
    by_digest = {}
    for c in cs:
        if c['digest'] not in by_digest or c['ts'] > by_digest[c['digest']]['ts']:
            by_digest[c['digest']] = c
    uniq = sorted(by_digest.values(), key=lambda c: c['ts'], reverse=True)

    def demoted(c):
        if kind != 'html' or ident in HOME_IDS:
            return False
        return c['digest'] in home_digests or len(owners[c['digest']]) >= 3

    good = [c for c in uniq if not demoted(c)]
    bad = [c for c in uniq if demoted(c)]
    for c in bad:
        c['demoted'] = True
    if uniq and uniq[0] in bad and good:
        stats['latest capture was a fallback (avoided)'] += 1
    if not good:
        stats['only fallback captures (kept as last resort)'] += 1
    manifest.append({'id': ident, 'kind': kind, 'cands': good + bad})
    stats[kind] += 1

json.dump(manifest, open(OUT, 'w'), indent=1)

print('identities:', len(manifest), ' (Common Crawl captures merged: %d)' % n_cc)
print('  identities only known from Common Crawl:',
      sum(1 for m in manifest if all(c.get('source') == 'cc' for c in m['cands'])))
print('  identities whose best candidate is from Common Crawl:',
      sum(1 for m in manifest if m['cands'][0].get('source') == 'cc'))
print('  identities only on the DreamHost server copy:',
      sum(1 for m in manifest if all(c.get('source') == 'server' for c in m['cands'])))
for k, v in stats.most_common():
    print('  %-48s %d' % (k, v))
first = Counter(m['cands'][0]['ts'][:4] for m in manifest)
print('year of first-choice capture:', dict(sorted(first.items())))
print('approx first-choice payload: %.1f MB'
      % (sum(m['cands'][0]['len'] for m in manifest) / 1e6))
