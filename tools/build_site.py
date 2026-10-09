#!/usr/bin/env python3
"""Build a static, offline-browsable 606mag.com from the recovered captures.

Every recovered page gets a clean static filename (main.php?id=80 -> main/id-80.html)
and every internal reference is rewritten to a relative path: HTML attributes, CSS
url(), and resource paths inside JavaScript (Dreamweaver rollovers, popups). Pages
are converted to UTF-8. Links to pages that were never archived point at
_missing.html; missing images become a transparent placeholder.

Also writes a report: missing targets ranked by how often they are referenced,
pages with PHP warnings, and a security scan for script/iframe injection.

The output directory is generated: it is rebuilt from scratch on every run.

Images lost everywhere but preserved as Windows Thumbs.db thumbnails (decoded by
thumbsdb.py + thumbjpeg.py into <project>/extras/thumbs) are used as low-res
stand-ins for the missing originals.

Usage: build_site.py MANIFEST ARCHIVE_DIR OUT_DIR REPORT_JSON
"""
import base64, hashlib, html, json, os, posixpath, re, shutil, sys
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cleanup import ENKODER, clean

man_path, arc, out, report_path = sys.argv[1:5]
manifest = json.load(open(man_path))
index = json.load(open(os.path.join(arc, '_index.json')))
blobs = os.path.join(arc, '_blobs')

SITE_HOSTS = {'606mag.com', 'www.606mag.com'}
BASE = 'http://www.606mag.com'

# ---------------------------------------------------------------- identities
def key_of(url):
    """Canonical lookup key: (decoded path, sorted query pairs without PHPSESSID)."""
    p = urlparse(url)
    pairs = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        while k.startswith('amp;'):
            k = k[4:]
        if k and k.lower() != 'phpsessid':
            pairs.append((k, v))
    return (unquote(p.path or '/'), tuple(sorted(pairs)))

MIME_EXT = {
    'text/html': '.html', 'text/css': '.css', 'text/xml': '.xml', 'text/plain': '.txt',
    'image/gif': '.gif', 'image/jpeg': '.jpg', 'image/png': '.png', 'image/bmp': '.bmp',
    'image/x-icon': '.ico', 'application/pdf': '.pdf', 'application/msword': '.doc',
    'application/x-shockwave-flash': '.swf', 'application/x-javascript': '.js',
    'application/javascript': '.js', 'text/javascript': '.js',
    'video/quicktime': '.mov', 'audio/mpeg': '.mp3',
}
COMPATIBLE = {'.html': {'.html', '.htm'}, '.jpg': {'.jpg', '.jpeg', '.jpe'},
              '.txt': {'.txt', '.db', '.log'}, '.xml': {'.xml', '.rss'}}
SCRIPT_EXTS = {'.php', '.php3', '.php4', '.phtml', '.asp', '.cgi', '.pl', ''}
MEDIA_EXTS = {'.gif', '.jpg', '.jpeg', '.png', '.bmp', '.swf', '.css', '.js', '.pdf',
              '.doc', '.mov', '.mp3', '.wav', '.avi', '.wmv', '.mpg', '.mpeg', '.ico'}
SAFE = re.compile(r'[^A-Za-z0-9._-]+')

def slug_query(pairs):
    s = '_'.join(SAFE.sub('-', k) + '-' + SAFE.sub('-', v) for k, v in pairs).strip('-_')
    if len(s) > 80 or not s:
        s = s[:60].rstrip('-_') + '-' + hashlib.sha1(repr(pairs).encode()).hexdigest()[:8]
    return s

def out_path_for(key, mime):
    path, pairs = key
    segs = [SAFE.sub('_', s) for s in path.split('/') if s]
    ext = MIME_EXT.get(mime.split(';')[0].strip().lower(), '')
    if path.endswith('/') or not segs:
        segs.append('index' + (ext or '.html'))
    else:
        stem, dot, e = segs[-1].rpartition('.')
        if not dot:
            stem, e = segs[-1], ''
        e = ('.' + e.lower()) if e else ''
        if ext and e not in COMPATIBLE.get(ext, {ext}):
            segs[-1] = (stem if e in SCRIPT_EXTS else segs[-1]) + ext
    if pairs:
        stem, _, e = segs[-1].rpartition('.')
        segs[-1] = stem
        segs.append(slug_query(pairs) + '.' + e)
    return '/'.join(segs)

# ---------------------------------------------------------------- reader-facing only
# Internal leftovers are not published (decided 2026-10-09); they stay in the vault.
INTERNAL = re.compile(
    r'^/(admin|simon|site|popupDEV|testimages)(/|$)'          # CMS, unrelated site, dev folders
    r'|^/(test\.htm|template\d*\.html|include\.php|main_include\.php|meta\.php'
    r'|comment\.(php|html)|index\.(new|letter)\.php)$'          # tests, drafts, include output
    r'|/thumbs\.db$|^/issues/general/New Folder/', re.I)
LISTING_TITLE = re.compile(rb'<title>\s*Index of /', re.I)

def internal(key, info):
    if INTERNAL.search(key[0]):
        return True
    if info['mime'].startswith('text/html'):
        with open(os.path.join(blobs, info['digest']), 'rb') as fh:
            return bool(LISTING_TITLE.search(fh.read(2048)))
    return False

# ---------------------------------------------------------------- mapping table
stats = Counter()
entries = []          # (key, out_path, info)
taken = set()         # lowercase out paths (macOS is case-insensitive)
lookup, lookup_ci = {}, {}
dropped = []

def claim(path):
    base, dot, ext = path.rpartition('.')
    if not dot:
        base, ext = path, ''
    cand, n = path, 2
    while cand.lower() in taken:
        cand = '%s-%d%s' % (base, n, '.' + ext if ext else '')
        n += 1
    taken.add(cand.lower())
    return cand

done = [(m['id'], index[m['id']]) for m in manifest
        if index.get(m['id'], {}).get('status') == 'done']
# canonical names first: fewer query params, then shorter paths
done.sort(key=lambda t: (len(key_of(t[0])[1]), len(t[0]), t[0]))
for ident, info in done:
    key = key_of(ident)
    mime = info['mime']
    if internal(key, info):
        stats['internal pages not published'] += 1
        continue
    ext_in_url = posixpath.splitext(key[0])[1].lower()
    if mime.startswith('text/html') and ext_in_url in MEDIA_EXTS - {'.html'}:
        dropped.append(ident)       # an HTML error page served at an image/css URL
        continue
    op = claim(out_path_for(key, mime))
    entries.append((key, op, info))
    lookup[key] = op
    lookup_ci.setdefault((key[0].lower(), key[1]), op)

# images that only survive as Thumbs.db thumbnails stand in for the lost originals
thumbs_dir = os.path.join(os.path.dirname(os.path.abspath(arc)), 'extras', 'thumbs')
thumb_files = []              # (source png, out path)
IMG_EXTS = {'.gif', '.jpg', '.jpeg', '.png', '.bmp'}
for dirpath, _, files in os.walk(thumbs_dir):
    if 'catalog.json' not in files:
        continue
    rel = os.path.relpath(dirpath, thumbs_dir).replace(os.sep, '/')
    folder = '/' if rel == '_root' else '/' + rel + '/'
    for item in json.load(open(os.path.join(dirpath, 'catalog.json'))):
        png = os.path.join(dirpath, (item.get('thumbnail') or '')[:-4] + '.png')
        k = key_of(folder + item['name'])
        if (item.get('thumbnail') and os.path.exists(png) and k not in lookup
                and posixpath.splitext(item['name'])[1].lower() in IMG_EXTS):
            op = claim(posixpath.splitext(out_path_for(k, ''))[0] + '.thumb.png')
            lookup[k] = op
            thumb_files.append((png, op))

# root-with-query aliases (/?general=x) -> /main.php?general=x, else the homepage
home = lookup.get(('/main.php', ()))
for m in manifest:
    if index.get(m['id'], {}).get('status') == 'alias':
        k = key_of(m['id'])
        tgt = lookup.get(('/main.php', k[1])) or home
        if tgt and k not in lookup:
            lookup[k] = tgt

def resolve(abs_url):
    key = key_of(abs_url)
    if key in lookup:
        return lookup[key]
    path, pairs = key
    tries = []
    if not path.endswith('/') and '.' not in path.rsplit('/', 1)[-1]:
        tries.append((path + '/', pairs))
    d = path if path.endswith('/') else None
    if d:
        tries += [(d + i, pairs) for i in ('index.php', 'index.html', 'index.htm')]
    for t in tries:
        if t in lookup:
            return lookup[t]
    return lookup_ci.get((path.lower(), pairs))

# ---------------------------------------------------------------- rewriting
missing = defaultdict(set)    # (kind, url) -> referring pages
recording = [True]            # off while rendering history snapshots

def relpath(target, page_out):
    return posixpath.relpath(target, posixpath.dirname(page_out) or '.')

def rewrite_ref(raw, page_url, page_out, kind):
    """Return the replacement for a reference, or None to leave it untouched."""
    val = html.unescape(raw).strip()
    low = val.lower()
    if not val or low.startswith(('#', 'javascript:', 'mailto:', 'data:', 'about:', 'tel:')):
        return None
    abs_url = urljoin(page_url, val)
    p = urlparse(abs_url)
    if p.scheme not in ('http', 'https') or p.hostname not in SITE_HOSTS:
        return None
    frag = ('#' + p.fragment) if p.fragment else ''
    target = resolve(abs_url)
    if target:
        if recording[0]:
            stats['links resolved'] += 1
        return relpath(target, page_out) + frag
    if kind == 'js':
        return None                       # may be a fragment of a concatenation
    if recording[0]:
        stats['links missing'] += 1
        missing[(kind, abs_url.split('#')[0])].add(page_out)
    if kind == 'img':
        return relpath('_missing.gif', page_out)
    if kind == 'page':
        return relpath('_missing.html', page_out) + '?u=' + quote(abs_url, safe='')
    return relpath(out_path_for(key_of(abs_url), ''), page_out)  # dead local path

JS_STR = re.compile(r'''(["'])((?:(?!\1)[^\\\n]|\\.)*)\1''')
RESOURCE = re.compile(r'''^[^\s<>"'()+]*?\.(?:gif|jpe?g|png|bmp|swf|css|js|html?|php|pdf|'''
                      r'''docx?|mp3|wav|aiff?|mov|avi|wmv|mpe?g|txt|xml|ico)(?:[?#][^\s<>"'+]*)?$''',
                      re.I)

def rewrite_js(code, page_url, page_out):
    def sub(m):
        q, s = m.group(1), m.group(2)
        if not RESOURCE.match(s):
            return m.group(0)
        new = rewrite_ref(s, page_url, page_out, 'js')
        return m.group(0) if new is None else q + new + q
    return JS_STR.sub(sub, code)

CSS_URL = re.compile(r'''url\(\s*(['"]?)([^'")]+)\1\s*\)''', re.I)
CSS_IMPORT = re.compile(r'''@import\s+(['"])([^'"]+)\1''', re.I)

def rewrite_css(css, page_url, page_out):
    def u(m):
        new = rewrite_ref(m.group(2), page_url, page_out, 'img')
        return m.group(0) if new is None else 'url(%s%s%s)' % (m.group(1), new, m.group(1))
    def imp(m):
        new = rewrite_ref(m.group(2), page_url, page_out, 'res')
        return m.group(0) if new is None else '@import %s%s%s' % (m.group(1), new, m.group(1))
    return CSS_IMPORT.sub(imp, CSS_URL.sub(u, css))

TAG = re.compile(r'''<([a-zA-Z][a-zA-Z0-9:-]*)((?:"[^"]*"|'[^']*'|[^'">])*)>''')
ATTR = re.compile(r'''([^\s"'>/=]+)(\s*=\s*)("[^"]*"|'[^']*'|[^\s"'>]+)''')
URL_ATTRS = {'href', 'src', 'background', 'action', 'lowsrc', 'dynsrc', 'usemap',
             'longdesc', 'data', 'poster'}
PAGE_TAGS = {'a', 'area', 'form', 'frame', 'iframe'}
IMG_ATTRS = {'background', 'lowsrc', 'dynsrc'}

def rewrite_tags(doc, page_url, page_out):
    def tag(m):
        name = m.group(1).lower()
        def attr(a):
            an, eq, raw = a.group(1).lower(), a.group(2), a.group(3)
            q = raw[0] if raw[0] in '"\'' else ''
            inner = raw[1:-1] if q else raw
            if an in URL_ATTRS:
                kind = ('page' if name in PAGE_TAGS else
                        'img' if (an == 'src' and name in ('img', 'input')) or an in IMG_ATTRS
                        else 'res')
                new = rewrite_ref(inner, page_url, page_out, kind)
                return a.group(0) if new is None else '%s%s"%s"' % (a.group(1), eq, new)
            if an.startswith('on'):
                return '%s%s%s%s%s' % (a.group(1), eq, q, rewrite_js(inner, page_url, page_out), q)
            if an == 'style':
                return '%s%s%s%s%s' % (a.group(1), eq, q, rewrite_css(inner, page_url, page_out), q)
            if name == 'param' and an == 'value' and RESOURCE.match(html.unescape(inner).strip()):
                new = rewrite_ref(inner, page_url, page_out, 'res')
                return a.group(0) if new is None else '%s%s"%s"' % (a.group(1), eq, new)
            if name == 'meta' and an == 'content' and re.search(r'url\s*=', inner, re.I):
                def mu(mm):
                    new = rewrite_ref(mm.group(2), page_url, page_out, 'page')
                    return mm.group(0) if new is None else mm.group(1) + new
                return '%s%s%s%s%s' % (a.group(1), eq, q,
                                       re.sub(r'''(url\s*=\s*)([^"';]+)''', mu, inner, flags=re.I), q)
            return a.group(0)
        return '<%s%s>' % (m.group(1), ATTR.sub(attr, m.group(2)))
    return TAG.sub(tag, doc)

BLOCK = re.compile(r'(<(script|style)\b[^>]*>)(.*?)(</\2\s*>)', re.I | re.S)

def strip_trackers(doc):
    return clean(doc, stats)

def rewrite_html(doc, page_url, page_out):
    base = re.search(r'''<base\s[^>]*href\s*=\s*["']?([^"' >]+)''', doc, re.I)
    if base:
        page_url = urljoin(page_url, base.group(1))
        doc = re.sub(r'<base\s[^>]*>', '', doc, flags=re.I)
    doc = rewrite_tags(doc, page_url, page_out)
    def block(m):
        fn = rewrite_js if m.group(2).lower() == 'script' else rewrite_css
        return m.group(1) + fn(m.group(3), page_url, page_out) + m.group(4)
    return BLOCK.sub(block, doc)

# ---------------------------------------------------------------- encoding
def decode(data):
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return ''.join(data[i:i+1].decode('cp1252', errors='strict') if data[i] not in
                       (0x81, 0x8d, 0x8f, 0x90, 0x9d) else chr(data[i])
                       for i in range(len(data))), 'cp1252'

META_CT = re.compile(r'''<meta[^>]+http-equiv\s*=\s*["']?content-type["']?[^>]*>''', re.I)
META_CS = re.compile(r'''<meta\s+charset\s*=\s*["']?[\w-]+["']?\s*/?>''', re.I)

def force_utf8(doc):
    doc = META_CT.sub('', doc)
    doc = META_CS.sub('', doc)
    head = re.search(r'<head\b[^>]*>', doc, re.I)
    tag = '<meta charset="utf-8">'
    if head:
        return doc[:head.end()] + tag + doc[head.end():]
    return tag + doc

# ---------------------------------------------------------------- security scan
SUSPICIOUS = [
    ('external script', re.compile(r'''<script[^>]+src\s*=\s*["']?https?://(?!(www\.)?606mag\.com)[^"' >]+''', re.I)),
    ('external iframe', re.compile(r'''<i?frame[^>]+src\s*=\s*["']?https?://(?!(www\.)?606mag\.com)[^"' >]+''', re.I)),
    ('hidden iframe', re.compile(r'''<iframe[^>]+((?<![\w-])width\s*=\s*["']?[01]["'\s>]|(?<![\w-])height\s*=\s*["']?[01]["'\s>]|display\s*:\s*none|visibility\s*:\s*hidden)''', re.I)),
    ('eval/unescape', re.compile(r'''eval\s*\(|document\.write\s*\(\s*unescape|String\.fromCharCode''', re.I)),
    ('hidden link block', re.compile(r'''<div[^>]+(display\s*:\s*none|left\s*:\s*-\d{3,}px)[^>]*>(?:(?!</div>).)*?<a\s''', re.I | re.S)),
    ('spam keywords', re.compile(r'''\b(viagra|cialis|casino|payday loan|replica watch|porn)\b''', re.I)),
]
security = defaultdict(list)

def scan(doc, page, ts):
    doc = ENKODER.sub('', doc)
    for label, rx in SUSPICIOUS:
        for hit in rx.finditer(doc):
            security[label].append({'page': page, 'ts': ts, 'snippet': hit.group(0)[:160]})

# ---------------------------------------------------------------- build
tmp = out.rstrip('/') + '.building'
if os.path.exists(tmp):
    shutil.rmtree(tmp)
os.makedirs(tmp)

warn_pages = []
for key, op, info in entries:
    data = open(os.path.join(blobs, info['digest']), 'rb').read()
    dest = os.path.join(tmp, op)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    mime = info['mime'].split(';')[0].strip().lower()
    page_url = info['url']
    if mime == 'text/html':
        doc, enc = decode(data)
        doc = strip_trackers(doc)
        scan(doc, op, info['ts'])
        doc = force_utf8(rewrite_html(doc, page_url, op))
        open(dest, 'w', encoding='utf-8').write(doc)
        stats['html pages'] += 1
        if info.get('warnings'):
            warn_pages.append({'page': op, 'ts': info['ts'], 'warnings': info['warnings']})
    elif mime == 'text/css':
        css, enc = decode(data)
        css = re.sub(r'''@charset\s+["'][^"']*["'];?''', '@charset "utf-8";', css, flags=re.I)
        open(dest, 'w', encoding='utf-8').write(rewrite_css(css, page_url, op))
        stats['stylesheets'] += 1
    else:
        open(dest, 'wb').write(data)
        stats['other files'] += 1

# ---------------------------------------------------------------- history
import datetime
HIST_NAMES = {'/main.php': ('homepage', 'the homepage'), '/': ('front-door', 'the front door')}

def nice(ts):
    return datetime.datetime.strptime(ts[:8], '%Y%m%d').strftime('%B %-d, %Y')

recording[0] = False
hist_sets = []
for ident in sorted(index):
    vers = index[ident].get('history') or []
    if len(vers) < 2:
        continue
    slug, label = HIST_NAMES.get(ident, (SAFE.sub('_', ident.strip('/')) or 'root', ident))
    outs = ['history/%s/%s-%s-%s_%s.html' % (slug, v['ts'][:4], v['ts'][4:6], v['ts'][6:8],
                                            v['ts'][8:14]) for v in vers]
    for i, (v, op) in enumerate(zip(vers, outs)):
        doc, enc = decode(open(os.path.join(blobs, v['digest']), 'rb').read())
        doc = strip_trackers(doc)
        scan(doc, op, v['ts'])
        doc = force_utf8(rewrite_html(doc, v['url'], op))
        link = lambda target, text: '<a style="color:#fff" href="%s">%s</a>' % (
            posixpath.relpath(target, posixpath.dirname(op)), text)
        bar = ('<div style="font:11px/1.6 Arial,sans-serif;background:#6C7393;color:#fff;'
               'padding:5px 10px;text-align:center">%s as captured on <b>%s</b>'
               ' &nbsp;&middot;&nbsp; %s &nbsp;&middot;&nbsp; %s &nbsp;&middot;&nbsp; %s</div>') % (
            label, nice(v['ts']),
            link(outs[i - 1], '&larr; older') if i else '<span style="opacity:.5">&larr; older</span>',
            link('history/index.html', 'all %d versions' % len(vers)),
            link(outs[i + 1], 'newer &rarr;') if i + 1 < len(vers) else
            '<span style="opacity:.5">newer &rarr;</span>')
        body = re.search(r'<body\b[^>]*>', doc, re.I)
        doc = doc[:body.end()] + bar + doc[body.end():] if body else bar + doc
        dest = os.path.join(tmp, op)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, 'w', encoding='utf-8').write(doc)
        stats['history snapshots'] += 1
    hist_sets.append((label, slug, list(zip(vers, outs))))
recording[0] = True

if hist_sets:
    parts = []
    for label, slug, items in hist_sets:
        parts.append('<h2>%s <small>(%d versions)</small></h2>' % (html.escape(label), len(items)))
        for year in sorted({v['ts'][:4] for v, _ in items}):
            links = ' '.join('<a href="%s">%s</a>' % (posixpath.relpath(o, 'history'),
                             datetime.datetime.strptime(v['ts'][:8], '%Y%m%d').strftime('%b %-d'))
                             for v, o in items if v['ts'][:4] == year)
            parts.append('<p><b>%s</b> &nbsp; %s</p>' % (year, links))
    open(os.path.join(tmp, 'history', 'index.html'), 'w', encoding='utf-8').write(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>606mag history</title><style>body{font:13px/1.7 Arial,sans-serif;color:#555;'
        'max-width:760px;margin:40px auto;padding:0 16px}h1{color:#878787;font-size:20px}'
        'h2{color:#6C7393;font-size:15px;margin-top:28px}small{color:#999;font-weight:normal}'
        'a{color:#6C7393;text-decoration:none;margin-right:6px;white-space:nowrap}a:hover{color:#878787}'
        'p{margin:4px 0}</style><h1>sixosix &middot; 606mag.com through the years</h1>'
        '<p>Pages whose content rotated are kept in every version the Wayback Machine saved, '
        'so nothing from the old front page is lost.</p>'
        '<p><a href="../index.html">&larr; back to the site</a></p>' + ''.join(parts))

for src, op in thumb_files:
    dest = os.path.join(tmp, op)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)
    stats['thumbnail stand-ins'] += 1

open(os.path.join(tmp, '_missing.gif'), 'wb').write(base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'))
open(os.path.join(tmp, '_missing.html'), 'w', encoding='utf-8').write('''<!doctype html>
<meta charset="utf-8"><title>Not archived</title>
<style>body{font:14px/1.5 Arial,sans-serif;color:#555;background:#fff;max-width:520px;margin:80px auto;padding:0 16px}
code{word-break:break-all;color:#6C7393}</style>
<h1 style="font-size:18px;color:#878787">This page wasn't saved</h1>
<p>The Wayback Machine never captured this page of 606mag.com, so it couldn't be recovered.</p>
<p>Original address: <code id="u"></code></p>
<p><a href="javascript:history.back()">&larr; go back</a></p>
<script>var u=new URLSearchParams(location.search).get('u');document.getElementById('u').textContent=u||'(unknown)';</script>
''')

if os.path.exists(out):
    shutil.rmtree(out)
os.replace(tmp, out)

# ---------------------------------------------------------------- report
miss = sorted(((k, sorted(v)) for k, v in missing.items()), key=lambda t: -len(t[1]))
report = {
    'stats': dict(stats),
    'dropped_html_at_media_urls': dropped,
    'pages_with_php_warnings': warn_pages,
    'thumbnail_stand_ins': [op for _, op in thumb_files],
    'missing': [{'kind': k[0], 'url': k[1], 'referenced_by': len(v), 'pages': v[:10]}
                for k, v in miss],
    'security': {k: v for k, v in security.items()},
}
json.dump(report, open(report_path, 'w'), indent=1)

print('built %s' % out)
for k, v in stats.most_common():
    print('  %-22s %d' % (k, v))
print('  missing targets        %d (img %d, page %d, res %d)' % (
    len(miss), sum(1 for k, _ in miss if k[0] == 'img'),
    sum(1 for k, _ in miss if k[0] == 'page'), sum(1 for k, _ in miss if k[0] == 'res')))
print('  pages w/ php warnings  %d' % len(warn_pages))
print('security scan:')
if not security:
    print('  nothing suspicious')
for k, v in security.items():
    print('  %-20s %d hits on %d pages' % (k, len(v), len({h['page'] for h in v})))
