#!/usr/bin/env python3
"""Extract sixosix's content into JSON for the modern (Astro) site, exactly as it was
last published.

Every page comes from its latest genuine as-published capture (the archive store);
the server copy's original article files are used only for pages never captured
(the server's 2010-era copies differ, e.g. issues 1-10 covers lost their links).
Each capture first gets the archive's cleanup (cleanup.py: ads, trackers, hidden
and commented-out spam links, comment and Q&A spam). From it we keep the original
page frame (issue picker, masthead, issue menu, footer) and the content cell, so
desktop rendering matches the last published design.

Links: old main.php links become the new readable URLs; sections not rebuilt yet
open their archived page; links that cannot resolve, and external links whose site
no longer works (tools/external_links.json), are de-linked keeping their text; the
"shop" masthead item is removed. Typos in the magazine's own links are fixed and
logged. Comments come from the database (comments.py policy, names only, no emails).

Usage: extract_content.py PROJECT_DIR OUT_DIR
"""
import html, json, os, re, sqlite3, sys, unicodedata
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse

project, out_dir = sys.argv[1:3]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cleanup import clean
from comments import EMAIL_ADDR, keep_comment, names_only, scrub
from renames import Resolver

SERVER = os.path.join(project, 'server-copy', 'extracted',
                      '606mag.com_DISABLED_FOR_MALWARE_SCRIPT_CONTACT_DREAMHOST_SUPPORT_cp')
db = sqlite3.connect(os.path.join(project, 'server-copy', 'sixosix.sqlite'))
site_map = json.load(open(os.path.join(project, 'tools', 'site_map.json')))
catalog = json.load(open(os.path.join(project, 'tools', 'catalog.json')))
arc_index = json.load(open(os.path.join(project, 'archive-raw', '_index.json')))
ext_path = os.path.join(project, 'tools', 'external_links.json')
external = json.load(open(ext_path)) if os.path.exists(ext_path) else {}
BLOBS = os.path.join(project, 'archive-raw', '_blobs')
BASE = 'http://www.606mag.com'
MAIN = BASE + '/main.php'
stats = Counter()
log = {'link fixes': [], 'unresolved assets': set(), 'de-linked internal': set(),
       'de-linked dead external': set(), 'unchecked external': set(), 'pages from server copy': []}

unq = lambda s: re.sub(r"\\(['\"\\])", r'\1', '' if s is None else str(s))

import codecs
# cp1252 leaves five bytes undefined; read those as latin-1 (same as the archive build)
codecs.register_error('latin1_fallback', lambda e: (e.object[e.start:e.end].decode('latin-1'), e.end))

def decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='latin1_fallback')

def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"['’]", '', s)
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-') or 'untitled'

def canon(url):
    p = urlparse(url)
    pairs = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        while k.startswith('amp;'):
            k = k[4:]
        if k and k.lower() != 'phpsessid':
            pairs.append((k, v))
    q = urlencode(sorted(pairs))
    return unquote(p.path or '/') + ('?' + q if q else '')

def published(ident):
    """Raw HTML of the latest genuine as-published capture of a page, or None. (Pages are
    cut apart first and only the kept parts are cleaned: some captures carry megabytes
    of spam comments.)"""
    v = arc_index.get(ident, {})
    if v.get('status') != 'done' or v.get('source') == 'server' or not v.get('mime', '').startswith('text/html'):
        return None
    return decode(open(os.path.join(BLOBS, v['digest']), 'rb').read())

# ------------------------------------------------------------------ catalog and URLs
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December']
issues, articles, used = {}, {}, {}
for n, name, folder, dark, light in db.execute(
        'SELECT issue, name, folder, color_dark, color_light FROM issues ORDER BY issue'):
    cat = catalog['issues'].get(str(n), {})
    issues[n] = {'number': n, 'name': unq(name), 'folder': unq(folder),
                 'colorDark': '#' + unq(dark).lstrip('#'), 'colorLight': '#' + unq(light).lstrip('#'),
                 'month': '%s 2004' % MONTHS[n - 1], 'url': '/issues/%d/' % n,
                 'sections': [{'name': s['section'], 'articles': [a['id'] for a in s['articles']]}
                              for s in cat.get('sections', [])]}
for aid, title, folder, issue, blurb in db.execute(
        'SELECT id, title, folder, issue, blurb FROM article_list ORDER BY id'):
    title, folder = unq(title).strip(), unq(folder).strip()
    if title.startswith('<') or 'L0V3' in title:            # 2009 injection guard
        continue
    cat = catalog['articles'].get(str(aid), {})
    slug = slugify(cat.get('menu_title') or title)
    while (issue, slug) in used:
        slug += '-%d' % aid
    used[(issue, slug)] = aid
    in_issue = issue in issues
    articles[aid] = {'id': aid, 'title': title, 'menuTitle': cat.get('menu_title') or title, 'slug': slug,
                     'issue': issue, 'section': cat.get('section'), 'folder': folder,
                     'issueFolder': issues[issue]['folder'] if in_issue else 'general',
                     'url': ('/issues/%d/%s/' % (issue, slug)) if in_issue else '/%s/' % slug,
                     'blurb': unq(blurb).strip() or None, 'pages': [], 'comments': [], 'views': 0}

def page_path(page):
    return page[5:] if re.fullmatch(r'index\d+', page) else page.lower()

def variant_key(params):
    """An article page variant: its parameters other than id (page=index is the default)."""
    d = {k: v for k, v in params.items() if k not in ('id', 'PHPSESSID')}
    if d.get('page', 'index') in ('', 'index'):
        d.pop('page', None)
    return tuple(sorted(d.items()))

def variant_path(vkey):
    d = dict(vkey)
    segs = [page_path(d.pop('page'))] if 'page' in d else []
    segs += ['%s-%s' % (k, slugify(v)) for k, v in sorted(d.items())]
    return ''.join(seg + '/' for seg in segs)

def article_url(aid, params=None):
    """URL of a published variant of an article, or None if that variant doesn't exist."""
    a = articles.get(aid)
    if not a:
        return None
    vkey = variant_key(params or {})
    return a['url'] + variant_path(vkey) if vkey in a['variants'] else None

# ------------------------------------------------------------------ link rewriting
ANCHOR = re.compile(r'<a\b([^>]*)>(.*?)</a\s*>', re.I | re.S)
AREA = re.compile(r'<area\b([^>]*)>', re.I)                     # image-map links (mix tapes)
LINK_TAG = re.compile(r'<link\b[^>]*>', re.I)                    # stylesheets are carried separately
HREF = re.compile(r'''\bhref\s*=\s*(["']?)([^"'\s>]*)\1''', re.I)
ASSET_ATTR = re.compile(r'''(\b(?:src|background)\s*=\s*)(["']?)([^"'\s>]+)\2''', re.I)
CSS_URL = re.compile(r'''url\(\s*(["']?)([^"')]+)\1\s*\)''', re.I)
POPUP = re.compile(r'''(MM_openBrWindow\(\s*['"])([^'"]+)(['"])''')

def is_own(host):
    return not host or host.lower() in ('606mag.com', 'www.606mag.com')

_paths = {k: v for k, v in site_map.items() if '?' not in k}
renamed = Resolver(_paths.keys(), lambda k: os.path.getsize(os.path.join(project, 'site', _paths[k]))
                   if os.path.exists(os.path.join(project, 'site', _paths[k])) else None)
_digest_cache = {}

def _file_digest(k):
    import hashlib
    if k not in _digest_cache:
        f = os.path.join(project, 'site', _paths[k])
        _digest_cache[k] = hashlib.sha1(open(f, 'rb').read()).hexdigest() if os.path.exists(f) else None
    return _digest_cache[k]
renamed.digest_of = _file_digest

def asset(url, base):
    if url.startswith(('data:', 'javascript:', '#', 'mailto:')):
        return url
    absu = urljoin(base, html.unescape(url).strip())
    if not is_own(urlparse(absu).hostname):
        return url
    hit = site_map.get(canon(absu))
    if hit:
        return '/archive/' + hit
    for alt in renamed.alternatives(canon(absu)):
        log.setdefault('resolved to renamed/original files', set()).add('%s -> %s' % (canon(absu), alt))
        return '/archive/' + site_map[alt]
    log['unresolved assets'].add(canon(absu))
    return '/archive/_missing.gif'

CURRENT = {}                                                  # variant being rewritten

def link_target(raw, base, where):
    """New href for a link, or None to de-link it."""
    raw = html.unescape(raw).strip()
    if not raw or raw.startswith(('#', 'javascript:')):
        return raw or None
    if raw.startswith('mailto:'):
        return raw
    absu = urljoin(base, raw)
    p = urlparse(absu)
    if p.scheme not in ('http', 'https'):                     # e.g. href="define:%20ironic" (dead in 2004)
        log.setdefault('de-linked non-web scheme', set()).add('%s: %s' % (where, raw))
        return None
    if not is_own(p.hostname):
        if 'cafeshops.com' in (p.hostname or ''):
            return None                                       # the dead CafePress shop
        rec = external.get(raw) or external.get(absu)
        if rec is None:
            log['unchecked external'].add(absu)
            return raw
        if not rec.get('ok'):
            log['de-linked dead external'].add('%s (%s)' % (absu, rec.get('why')))
            return None
        return raw
    q = dict(parse_qsl(p.query.replace('&amp;', '&'), keep_blank_values=True))
    q.pop('PHPSESSID', None)
    # a blank value only means something for song= and stop= (those blank pages were published
    # and differ from the page without them); elsewhere it equals the bare page
    q = {k: v for k, v in q.items() if v != '' or k in ('song', 'stop')}
    if 'pahe' in q:                                           # the magazine's typo: pahe= for page=
        q['page'] = q.pop('pahe')
        log['link fixes'].append('%s: pahe= -> page=' % where)
    if p.path.endswith('main.php') or p.path in ('', '/'):
        if q.get('id', '').isdigit() and int(q['id']) in articles and articles[int(q['id'])]['issue'] in issues:
            u = article_url(int(q['id']), q)
            if not u and CURRENT.get('page') and 'page' not in q:      # e.g. stop=N links on page 2
                u = article_url(int(q['id']), dict(q, page=CURRENT['page']))
            if not u and 'page' in q:                                     # e.g. img=N captured without page=
                u = article_url(int(q['id']), {k: v for k, v in q.items() if k != 'page'})
            if u:
                return u
            log.setdefault('missing variants', set()).add(canon(absu))
        elif q.get('issue_id', '').isdigit() and int(q['issue_id']) in issues:
            return issues[int(q['issue_id'])]['url']
        elif p.path.endswith('main.php') and not q:
            return '/issues/12/'
    hit = site_map.get(canon(urlunsplit_query(p, q)))
    if hit:
        return '/archive/' + hit
    gen = articles.get(int(q['id'])) if (p.path.endswith('main.php') or p.path in ('', '/')) and q.get('id', '').isdigit() else None
    if gen and gen['issueFolder'] == 'general':               # a general article (e.g. garden of eden): its section page
        hit = site_map.get('/main.php?general=%s' % gen['folder'])
        if hit:
            return '/archive/' + hit
    log['de-linked internal'].add(canon(absu))
    return None

def urlunsplit_query(p, q):
    return '%s://%s%s%s' % (p.scheme or 'http', p.netloc or 'www.606mag.com', p.path,
                            ('?' + urlencode(sorted(q.items()))) if q else '')

def rewrite(fragment, base, where):
    def anchor(m):
        attrs, inner = m.group(1), m.group(2)
        h = HREF.search(attrs)
        if not h:
            return m.group(0)
        new = link_target(h.group(2), base, where)
        g = CURRENT.get('_article', {}).get('gallery', {}).get(CURRENT.get('_page'))
        arrow = re.search(r'''<img\b[^>]*\bsrc\s*=\s*["']?[^"'\s>]*/(left|previous|right|next)\.gif''', inner, re.I)
        if arrow and new in ('#', '') and CURRENT.get('_article') and 'onclick' not in attrs.lower():
            seq = [pg for pg in CURRENT['_article'].get('pageSeq', [])]
            cur = CURRENT.get('_page', 'index')
            if cur in seq:
                j = seq.index(cur) + (-1 if arrow.group(1).lower() in ('left', 'previous') else 1)
                if 0 <= j < len(seq):
                    u = article_url(CURRENT['_article']['id'], {'page': seq[j]})
                    log.setdefault('dead arrows linked to previous/next page', set()).add(where)
                    return '<a%s>%s</a>' % (attrs[:h.start()] + 'href="%s"' % u + attrs[h.end():], inner)
            log.setdefault('dead arrows de-linked (no page there)', set()).add(where)
            return inner
        if g and (new in ('#', '') or new is None) and 'onclick' not in attrs.lower():
            for raw in IMG_SRC.findall(inner):
                mm = THUMB.match(posixpath.basename(canon(urljoin(base, html.unescape(raw)))))
                if mm and int(mm['num']) in g['fulls']:
                    u = article_url(CURRENT['_article']['id'], {'page': CURRENT['_page'], 'img': str(int(mm['num']))})
                    if u:
                        log.setdefault('thumbnails linked to their view', set()).add(where)
                        return '<a%s>%s</a>' % (attrs[:h.start()] + 'href="%s"' % u + attrs[h.end():], inner)
        if new is None:
            thumb = re.search(r'src="([^"]*?)_?Tx?\.(jpg|gif|jpeg|png)"', inner, re.I)
            if thumb and re.search(r'[?&]id=\d', h.group(2)):
                full = '%s.%s' % (thumb.group(1), thumb.group(2))
                hit = site_map.get(canon(urljoin(base, full)))
                if hit:
                    log.setdefault('thumbnails linked to full-size photo', []).append(where + ' -> ' + full)
                    return '<a%s>%s</a>' % (attrs[:h.start()] + 'href="/archive/%s"' % hit + attrs[h.end():], inner)
            target = html.unescape(h.group(2)).strip()
            pu = urlparse(urljoin(base, target))
            if target and pu.scheme in ('http', 'https') and is_own(pu.hostname):
                # a dead link to the magazine's own site keeps its link look and opens the archive's
                # "not archived" notice, as the archive does (dead external links are de-linked)
                log.setdefault('dead own-site links to the not-archived notice', set()).add(where)
                return '<a%s>%s</a>' % (attrs[:h.start()] + 'href="/archive/_missing.html?u=%s"' % quote(urljoin(base, target), safe='') + attrs[h.end():], inner)
            return inner                                          # de-link, keep the words
        return '<a%s>%s</a>' % (attrs[:h.start()] + 'href="%s"' % html.escape(new, quote=True) + attrs[h.end():], inner)
    def area(m):
        h = HREF.search(m.group(1))
        if not h:
            return m.group(0)
        new = link_target(h.group(2), base, where)
        if new is None:
            return ''
        return '<area%s>' % (m.group(1)[:h.start()] + 'href="%s"' % html.escape(new, quote=True) + m.group(1)[h.end():])
    fragment = LINK_TAG.sub('', fragment)
    fragment = ANCHOR.sub(anchor, fragment)
    fragment = AREA.sub(area, fragment)
    fragment = ASSET_ATTR.sub(lambda m: m.group(1) + '"' + asset(m.group(3), base) + '"', fragment)
    fragment = POPUP.sub(lambda m: m.group(1) + (link_target(m.group(2), base, where) or asset(m.group(2), base)) + m.group(3), fragment)
    CURRENT.clear()
    return CSS_URL.sub(lambda m: 'url("%s")' % asset(m.group(2), base), fragment)

# ------------------------------------------------------------------ cutting a published page apart
MAIN_TD = re.compile(r'<td\b([^>]*class="main_cell_margin"[^>]*)>', re.I)
# The menu's "new comments" box (the five latest comments on the whole site) was generated on
# every request: each page keeps the box its own capture shows. The rest of a captured menu is
# always its issue's menu (only the "ISSUE N" label varied, taken from the visitor's session).
NEW_COMMENTS = re.compile(r'<span class="submenu_title"[^>]*>\s*new comments\s*</span>\s*<table\b.*?</table\s*>', re.I | re.S)
NEW_COMMENTS_SLOT = '<!--new comments-->'
# end of the comments block: its last divider row, or the header bar when there were no comments
COMMENTS_END = re.compile(r'(?:font-size:\s*3px;?"\s*>\s*&nbsp;\s*</td>|height:\s*5px;?"\s*>\s*</td>)\s*</tr>\s*</table\s*>', re.I)

def parts(doc):
    """issues box, masthead, menu, content cell (attrs + html), footer, title, page css href."""
    i_issues, i_nav = doc.find('<div id="issues"'), doc.find('<div id="navBar"')
    i_after_nav = min([x for x in (doc.find('<div id="ad_right"', i_nav), doc.find('<div id="content"', i_nav)) if x > 0])
    menu = re.search(r'class="submenu_maincell">(.*?)</td>\s*<td\b[^>]*class="main_cell_margin"', doc, re.S | re.I)
    td = MAIN_TD.search(doc)
    foot = re.search(r'<div id="footer">.*?</div>.*?</div>', doc[td.end():], re.S)
    end = td.end() + foot.start() if foot else len(doc)
    form = doc.find('<form name="email"', td.end(), end)
    tail = ''
    if form > 0:
        last = None
        for last in COMMENTS_END.finditer(doc, form, end):
            pass
        if last:   # markup the article continued with after the comments block (issue 2 asphalt, page 2)
            es = doc.find('<div id="email_submit"', last.end(), end)
            t = clean(doc[last.end():es if es > 0 else end], Counter())
            if re.sub(r'<(?!img\b)[^>]*>|&nbsp;|\s', '', re.sub(r'<!--.*?-->', '', t, flags=re.S)):
                tail = t.strip()
        end = doc.rfind('<table', td.end(), form)
    content = doc[td.end():end].strip()
    if form > 0:          # the comments block opens with <br><br> (Comments.astro adds it back);
        content = re.sub(r'<br>\s*<br>$', '', content, flags=re.I).rstrip()   # any more are the article's
    title = re.search(r'<title>(.*?)</title>', doc, re.S | re.I)
    css = re.search(r'<link href="(issues/[^"]+/local\.css)"[^>]*>\s*<script', doc) or \
          [m for m in re.finditer(r'<link href="(issues/[^"]+/[^"/]+/local\.css)"', doc)]
    page_css = css.group(1) if hasattr(css, 'group') else (css[-1].group(1) if css else None)
    return {'issues': clean(doc[i_issues:i_nav], stats), 'nav': clean(doc[i_nav:i_after_nav], stats),
            'menu': clean(menu.group(1), stats) if menu else '',
            'mainAttrs': td.group(1), 'content': clean(content, stats),
            'footer': clean(foot.group(0), stats) if foot else '',
            'title': html.unescape(re.sub(r'\s+', ' ', title.group(1))).strip() if title else '',
            'pageCss': page_css, 'tail': tail, 'comments': form > 0}

def css_text(href, base):
    """Content of a page stylesheet (its archived copy), links rewritten."""
    if not href:
        return ''
    hit = site_map.get(canon(urljoin(base, href)))
    path = os.path.join(project, 'site', hit) if hit else None
    if not path or not os.path.exists(path):
        f = os.path.join(SERVER, urlparse(urljoin(base, href)).path.lstrip('/'))
        path = f if os.path.exists(f) else None
    if not path:
        return ''
    text = open(path, encoding='utf-8', errors='replace').read()
    if '<?' in text:                                          # PHP template, not usable as-is
        return ''
    return CSS_URL.sub(lambda m: 'url("%s")' % asset(m.group(2), urljoin(base, href)), text)

SHOP_CELL = re.compile(r'<td\b[^>]*>\s*<img[^>]*header_deviders[^>]*>\s*</td>\s*<td\b[^>]*>\s*<div[^>]*>\s*(?:&nbsp;)?\s*'
                       r'<a\b[^>]*cafeshops[^>]*>.*?</a>\s*</div>\s*</td>', re.I | re.S)

# every published variant (page / img / song / choice ...) and every server-copy page
for a in articles.values():
    a['variants'] = {}
for k, v in arc_index.items():
    p = urlparse(k)
    if p.path != '/main.php' or v.get('status') != 'done' or v.get('source') == 'server' \
            or not v.get('mime', '').startswith('text/html'):
        continue
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    if q.get('id', '').isdigit() and int(q['id']) in articles:
        articles[int(q['id'])]['variants'].setdefault(variant_key(q), k)
for a in articles.values():
    folder = os.path.join(SERVER, 'issues', a['issueFolder'], a['folder'])
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if re.fullmatch(r'index\d*\.php', f):
                a['variants'].setdefault(variant_key({'page': f[:-4]}), None)

# ------------------------------------------------------------------ issues: frame, theme, cover
for n, iss in issues.items():
    doc = published('/main.php?issue_id=%d' % n)
    p = parts(doc)
    nav = SHOP_CELL.sub('', p['nav'])
    iss['frame'] = {k: rewrite(v, MAIN, iss['url']) for k, v in
                    (('issues', p['issues']), ('nav', nav), ('menu', p['menu']), ('footer', p['footer']))}
    box = NEW_COMMENTS.search(iss['frame']['menu'])
    if not box:
        sys.exit('issue %d: menu has no "new comments" box' % n)
    iss['frame']['newComments'] = box.group(0)
    iss['frame']['menu'] = iss['frame']['menu'][:box.start()] + NEW_COMMENTS_SLOT + iss['frame']['menu'][box.end():]
    theme = re.search(r'<style[^>]*>(.*?)</style>', doc, re.S | re.I)
    iss['themeCss'] = CSS_URL.sub(lambda m: 'url("%s")' % asset(m.group(2), MAIN),
                                  theme.group(1).replace('<!--', '').replace('-->', '').replace('?>', '')) if theme else ''
    iss['title'] = p['title']
    iss['coverAttrs'] = p['mainAttrs']
    iss['coverHtml'] = rewrite(p['content'], MAIN, iss['url'])
    iss['coverCss'] = css_text(p['pageCss'], MAIN)

# ------------------------------------------------------------------ article pages
PHP = re.compile(r'<\?(?:php)?(.*?)\?>', re.S)

def swap_view(body, a, page, k, n):
    g = a['gallery'][page]
    main_from, main_to = '/archive/' + site_map[g['fulls'][k]], '/archive/' + site_map[g['fulls'][n]]
    body = body.replace('"%s"' % main_from, '"%s"' % main_to)
    def state_paths(num):
        return {x: '/archive/' + site_map[p] for x, (p, m) in g['thumbs'][num].items()}
    sk, sn = state_paths(k), state_paths(n)
    if len(sk) == 2 and len(sn) == 2:
        # which state marks "current" on the template: the one thumbnail K is shown in
        cur = next((x for x, path in sk.items() if '"%s"' % path in body), None)
        if cur is not None:
            body = body.replace('"%s"' % sk[cur], '"\x00K\x00"').replace('"%s"' % sn[not cur], '"%s"' % sn[cur])
            body = body.replace('"\x00K\x00"', '"%s"' % sk[not cur])
    return body

def server_page(a, name):
    f = os.path.join(SERVER, 'issues', a['issueFolder'], a['folder'], name + '.php')
    if not os.path.exists(f):
        return None
    text = PHP.sub('', decode(open(f, 'rb').read()))
    text = clean(text, stats)
    body = re.search(r'<body[^>]*>(.*?)(?:</body>|$)', text, re.S | re.I)
    css = ''.join(css_text(h, '%s/issues/%s/%s/' % (BASE, a['issueFolder'], a['folder']))
                  for h in re.findall(r'<link[^>]+href=["\']?([^"\'\s>]+local\.css)', text, re.I))
    return (body.group(1) if body else text).strip(), css

def page_order(names):
    def key(n):
        if n == 'index':
            return (0, 0, '')
        m = re.fullmatch(r'index(\d+)', n)
        return (1, int(m.group(1)), '') if m else (2, 0, n)
    return sorted(set(names), key=key)

# Photo views (img=N) that were linked but never captured: rebuilt from a captured
# sibling view of the same page, swapping only the main photo (M.ext -> N.ext), when
# that photo file exists. Each one is logged.
for a in articles.values():
    by_page = {}
    for vkey, ident in a['variants'].items():
        d = dict(vkey)
        if 'img' in d and isinstance(ident, str):
            by_page.setdefault(d.get('page', 'index'), {})[d['img']] = ident
    for page, views in by_page.items():
        sib_img, sib_ident = sorted(views.items())[-1]
        raw = published(sib_ident) or ''
        for n in set(re.findall(r'main\.php\?(?:[^"\'>]*&(?:amp;)?)?id=%d\b[^"\'>]*?img=(\w+)' % a['id'], raw)):
            vk = variant_key({'page': page, 'img': n})
            if vk not in a['variants']:
                a['variants'][vk] = ('rebuilt', sib_ident, sib_img, n)

# Photo galleries: a page with a numbered thumbnail strip (name 1T.jpg / bwl_01_T.jpg / ..._Tx.jpg)
# and a main photo (the full-size of one thumbnail). Every thumbnail whose full-size photo exists
# gets an in-article view page (page=P&img=N): the captured one, or one rebuilt from the page's
# template by swapping the main photo and the "current" thumbnail marker. Thumbnails left as
# dead "#" placeholders by the server copy link to their view.
import posixpath
THUMB = re.compile(r'^(?P<prefix>.*?)(?P<num>\d+)(?P<sep>_?)(?P<t>[Tt])(?P<x>x?)\.(?P<ext>jpe?g|gif|png)$', re.I)
IMG_SRC = re.compile(r'''<img\b[^>]*?\bsrc\s*=\s*["']?([^"'\s>]+)''', re.I)
SERVER_BASE = lambda a: '%s/issues/%s/%s/' % (BASE, a['issueFolder'], a['folder'])

def page_source(a, page):
    """(ident, html, base) of an article's base page (no img=) as published, else the server copy."""
    ident = a['variants'].get(variant_key({'page': page}))
    if isinstance(ident, str):
        doc = published(ident)
        if doc:
            return ident, doc, MAIN
    f = os.path.join(SERVER, 'issues', a['issueFolder'], a['folder'], page + '.php')
    if os.path.exists(f):
        return None, PHP.sub('', decode(open(f, 'rb').read())), SERVER_BASE(a)
    return None, '', None

def full_of(thumb_path, m):
    folder = posixpath.dirname(thumb_path)
    for ext in (m['ext'], 'jpg', 'gif', 'jpeg', 'png'):
        cand = posixpath.join(folder, m['prefix'] + m['num'] + '.' + ext)
        if cand in site_map:
            return cand
    return None

HASH_THUMB = re.compile(r'''<a\b[^>]*\bhref\s*=\s*["']#["'][^>]*>\s*<img\b[^>]*?\bsrc\s*=\s*["']?([^"'\s>]+)''', re.I)

def linked_views(a):
    """(page, N) photo views the original pages actually link to: captured img= links, plus
    thumbnails the server copy left as dead '#' placeholders. Views are never invented."""
    out = set()
    for vkey, ident in a['variants'].items():
        if isinstance(ident, str):
            for href in re.findall(r'''href\s*=\s*["']?([^"'\s>]*\bid=%d\b[^"'\s>]*)''' % a['id'], published(ident) or ''):
                q = dict(parse_qsl(html.unescape(href).split('?', 1)[-1]))
                if q.get('img', '').isdigit():
                    out.add((q.get('page', dict(vkey).get('page', 'index')) or 'index', int(q['img'])))
    return out

for a in articles.values():
    a['gallery'] = {}
    wanted = linked_views(a)
    for page in sorted({dict(vk).get('page', 'index') for vk in a['variants']}):
        ident, src, base = page_source(a, page)
        if not src:
            continue
        for raw in HASH_THUMB.findall(src):
            m = THUMB.match(posixpath.basename(canon(urljoin(base, html.unescape(raw)))))
            if m:
                wanted.add((page, int(m['num'])))
        thumbs = {}
        for raw in IMG_SRC.findall(src):
            path = canon(urljoin(base, html.unescape(raw)))
            m = THUMB.match(posixpath.basename(path))
            if m and path in site_map and full_of(path, m):
                thumbs.setdefault(int(m['num']), {})[(m['x'] or '').lower() == 'x'] = (path, m)
        fulls = {}
        for n, states in thumbs.items():
            path, m = next(iter(states.values()))
            fulls[full_of(path, m)] = n
        shown = [fulls[canon(urljoin(base, html.unescape(r)))] for r in IMG_SRC.findall(src)
                 if canon(urljoin(base, html.unescape(r))) in fulls]
        if len(fulls) < 2 or not shown:
            continue
        k = shown[0]
        a['gallery'][page] = {'shown': k, 'thumbs': thumbs, 'fulls': {n: f for f, n in fulls.items()}}
        for n in fulls.values():
            vk = variant_key({'page': page, 'img': str(n)})
            if vk not in a['variants'] and (page, n) in wanted:
                a['variants'][vk] = ('view', ident, page, k, n)

def base_pages(a):
    names = {dict(vk).get('page', 'index') for vk in a['variants'] if 'img' not in dict(vk) and len(vk) <= 1}
    return sorted(names, key=lambda n: variant_order(variant_key({'page': n})))

def variant_order(vkey):
    d = dict(vkey)
    page = d.pop('page', 'index')
    m = re.fullmatch(r'index(\d+)', page)
    rank = (0, 0, '') if page == 'index' else (1, int(m.group(1)), '') if m else (2, 0, page)
    return rank + tuple((k, int(v) if v.isdigit() else 10**6, v) for k, v in sorted(d.items()))

for a in articles.values():
    a['pageSeq'] = base_pages(a)

# A gallery page that only survives as a (damaged) server copy, but whose views were captured,
# is shown as its first captured view, as published: without img= the live site showed that view.
for a in articles.values():
    for vkey, ident in list(a['variants'].items()):
        if ident is None and 'img' not in dict(vkey):
            page = dict(vkey).get('page', 'index')
            views = sorted((vk for vk, i in a['variants'].items()
                            if isinstance(i, str) and dict(vk).get('page', 'index') == page and 'img' in dict(vk)),
                           key=variant_order)
            first = re.match(r'\d+', dict(views[0]).get('img', '')) if views else None
            if first and int(first.group(0)) == 1:                # only if view 1 itself was captured
                a['variants'][vkey] = a['variants'][views[0]]
                log.setdefault('server pages replaced by their first captured view', []).append(
                    a['url'] + variant_path(vkey) + ' <- ' + variant_path(views[0]))

EMPTY_PAGE = re.compile(r'&nbsp;|\s')
COMMENT_COLOR = re.compile(r'<span style="color: (#[0-9A-Fa-f]{6});">subject</span>')
comment_colors = {n: Counter() for n in issues}
for a in articles.values():
    kept = []
    for vkey in sorted(a['variants'], key=variant_order):
        ident = a['variants'][vkey]
        where = a['url'] + variant_path(vkey)
        CURRENT.clear()
        CURRENT.update(dict(vkey))
        swap = view = new_comments = None
        shows_comments, tail = None, ''
        if isinstance(ident, tuple) and ident[0] == 'view':     # a gallery view rebuilt from its page
            _, ident, vpage, k, n = ident
            view = (vpage, k, n)
            if ident is None:                                 # template is the server-copy page
                CURRENT.clear(); CURRENT.update(dict(vkey)); CURRENT['_article'] = a; CURRENT['_page'] = vpage
                sp = server_page(a, vpage)
                if not sp:
                    continue
                body = rewrite(sp[0], SERVER_BASE(a), where)
                kept.append({'path': variant_path(vkey), 'url': where,
                             'mainAttrs': 'valign="top" width="682" class="main_cell_margin"',
                             'html': swap_view(body, a, vpage, k, n), 'css': sp[1], 'newComments': None, 'comments': None})
                log.setdefault('gallery views rebuilt', []).append(where)
                continue
        elif isinstance(ident, tuple):                    # a view rebuilt from a sibling
            _, ident, sib_img, n = ident
            swap = (sib_img, n)
        doc = published(ident) if ident else None
        if doc and swap:
            folder = '/issues/%s/%s/images/' % (a['issueFolder'], a['folder'])
            main = re.search(r'%s%s\.(jpg|gif|jpeg|png)' % (re.escape(folder), re.escape(swap[0])), doc, re.I)
            target = main and site_map.get('%s%s.%s' % (folder, swap[1], main.group(1)))
            if not target:
                continue
            doc = doc.replace(main.group(0), '%s%s.%s' % (folder, swap[1], main.group(1)))
            log.setdefault('views rebuilt from a sibling', []).append('%s (from img=%s)' % (where, swap[0]))
        if doc:
            p = parts(doc)
            CURRENT['_article'] = a; CURRENT['_page'] = dict(vkey).get('page', 'index')
            body, css, attrs = rewrite(p['content'], MAIN, where), css_text(p['pageCss'], MAIN), p['mainAttrs']
            shows_comments = p['comments']
            if a['issue'] in comment_colors:
                comment_colors[a['issue']].update(COMMENT_COLOR.findall(doc))
            if p['tail']:
                CURRENT.update(dict(vkey)); CURRENT['_article'] = a; CURRENT['_page'] = dict(vkey).get('page', 'index')
                tail = rewrite(p['tail'], MAIN, where)
            box = NEW_COMMENTS.search(p['menu'])
            CURRENT.clear()                                   # menu links take no page context (as in the issue menus)
            new_comments = rewrite(box.group(0), MAIN, where) if box else None
            if view:
                body = swap_view(body, a, view[0], view[1], view[2])
                log.setdefault('gallery views rebuilt', []).append(where)
            a.setdefault('pageTitle', p['title'])
        else:
            CURRENT['_article'] = a; CURRENT['_page'] = dict(vkey).get('page', 'index')
            sp = server_page(a, dict(vkey).get('page', 'index'))
            if not sp:
                continue
            body, css = sp
            attrs = 'valign="top" width="682" class="main_cell_margin"'
            body = rewrite(body, '%s/issues/%s/%s/' % (BASE, a['issueFolder'], a['folder']), where)
            log['pages from server copy'].append(where)
        if not EMPTY_PAGE.sub('', re.sub(r'<(?!img\b)[^>]*>', '', body)).strip():
            log.setdefault('pages with no content (PHP errors only)', []).append(where)
            continue
        rec = {'path': variant_path(vkey), 'url': where, 'mainAttrs': attrs, 'html': body, 'css': css,
               'newComments': new_comments, 'comments': shows_comments}
        if tail:
            rec['tail'] = tail
        kept.append(rec)
    # pages with no capture (server copy) show the comments block as the article's captured pages did
    shown = [pg['comments'] for pg in kept if pg['comments'] is not None]
    for pg in kept:
        if pg['comments'] is None:
            pg['comments'] = any(shown) if shown else pg['path'] == ''
    a['pages'] = kept

# the comment colour each issue was published with (issues 1 and 2 differ from the database colour)
for n, iss in issues.items():
    top = comment_colors[n].most_common(1)
    iss['commentColor'] = top[0][0] if top else iss['colorLight']
    if iss['commentColor'] != iss['colorLight']:
        log.setdefault('comment colour as published (differs from the database)', []).append('%d: %s' % (n, iss['commentColor']))

# ------------------------------------------------------------------ comments, views
CHICAGO = ZoneInfo('America/Chicago')     # the published dates match Chicago time on 682 of 684 checkable comments
for aid, ts, name, link_, subject, text in db.execute(
        'SELECT article_id, insert_date, name, link, subject, comment FROM comments ORDER BY insert_date'):
    when = datetime.fromtimestamp(int(ts), timezone.utc)
    name, subject, text = unq(name), unq(subject), unq(text)
    if aid in articles and keep_comment(when, name, text, subject, link_ or ''):
        safe = html.escape(scrub(re.sub(r'<[^>]+>', ' ', text)))   # line breaks kept exactly (shown with nl2br)
        articles[aid]['comments'].append({
            'date': when.astimezone(CHICAGO).strftime('%m.%d.%Y'),   # shown in the server's (Chicago) time, as published
            'name': html.unescape(names_only(name)).strip() or 'anonymous',
            'subject': scrub(html.unescape(subject)).strip(),
            'text': safe})
for aid, views in db.execute('SELECT article_id, views FROM article_views'):
    if str(aid).isdigit() and int(aid) in articles:
        articles[int(aid)]['views'] = views

# ------------------------------------------------------------------ write
os.makedirs(out_dir, exist_ok=True)
json.dump(list(issues.values()), open(os.path.join(out_dir, 'issues.json'), 'w'), indent=1, ensure_ascii=False)
# Redirect map for old links (served as redirects.json, used by the 404 page): article variant
# (sorted old query without id) -> new path, issue -> path, any other old address -> archive file.
redirects = {'articles': {}, 'issues': {str(n): i['url'].lstrip('/') for n, i in issues.items()},
             'archive': {k: v for k, v in site_map.items()}}
for a in articles.values():
    if a['issue'] in issues and not a['pages'] and a['variants']:      # never had content: its issue
        redirects['articles'][str(a['id'])] = {'base': issues[a['issue']]['url'].lstrip('/'), 'pages': {}}
    if a['issue'] not in issues or not a['pages']:
        continue
    kept_paths = {pg['path'] for pg in a['pages']}
    redirects['articles'][str(a['id'])] = {
        'base': a['url'].lstrip('/'),
        'pages': {urlencode(sorted(vk)): variant_path(vk) for vk in a['variants'] if variant_path(vk) in kept_paths}}
public = os.path.join(os.path.dirname(out_dir.rstrip('/')), '..', 'public')
os.makedirs(public, exist_ok=True)
json.dump(redirects, open(os.path.join(public, 'redirects.json'), 'w'), separators=(',', ':'), sort_keys=True)

for a in articles.values():
    a.pop('variants', None)
    a.pop('gallery', None)
    a.pop('pageSeq', None)
json.dump([a for a in articles.values() if a['pages']], open(os.path.join(out_dir, 'articles.json'), 'w'),
          indent=1, ensure_ascii=False)
json.dump({k: sorted(v) if isinstance(v, set) else v for k, v in log.items()},
          open(os.path.join(project, 'tools', 'extract_report.json'), 'w'), indent=1)
pages = sum(len(a['pages']) for a in articles.values())
print('issues: %d   articles with pages: %d   pages: %d (from server copy: %d)   comments: %d' % (
    len(issues), sum(1 for a in articles.values() if a['pages']), pages, len(log['pages from server copy']),
    sum(len(a['comments']) for a in articles.values())))
print('link typo fixes: %d   de-linked internal: %d   de-linked dead external: %d   unchecked external: %d   unresolved assets: %d' % (
    len(log['link fixes']), len(log['de-linked internal']), len(log['de-linked dead external']),
    len(log['unchecked external']), len(log['unresolved assets'])))
print('links to article variants that were never published: %d' % len(log.get('missing variants', ())))
print('cleanup on extracted pages:', dict(stats))
