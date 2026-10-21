#!/usr/bin/env python3
"""Write web/src/data/seo.json: what search engines and link previews show for each rebuilt
page. Nothing on the pages themselves changes; the site's <head> reads this file
(web/src/lib/seo.ts).

For every page: a <title> and meta description in the magazine's own lowercase style, and
the picture a shared link shows (with its size). For every article: its credits ("words by",
"photos by"...) and teaser line. Everything comes from what the 2004 pages already say:
the article and issue data (web/src/data), the text of each page, and the alt text of its
images (tools/image_alt.json: bylines and title lettering are transcribed there). Reader
comments are never used, and neither are a photo shoot's credit lists (models, stylists).

Pages published twice (a gallery's opening page and its "photo 1", the same photo under two
addresses, one article issued twice) name the first copy as canonical, so the copies don't
compete in search.

It also writes tools/image_alt_context.json: alt text for the articles' photos that says which
article each is from, by whom and (for the lead photo) what the article is about, followed by
what the picture shows. tools/apply_alt_text.py and tools/make_sitemap.py prefer it over the
plain description in tools/image_alt.json.

Rerun after changing the content or tools/image_alt.json:  python3 tools/make_seo.py
"""
import html, json, os, re, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'web', 'src', 'data')
SITE = os.path.join(ROOT, 'site')
articles = json.load(open(os.path.join(DATA, 'articles.json'), encoding='utf-8'))
issues = {i['number']: i for i in json.load(open(os.path.join(DATA, 'issues.json'), encoding='utf-8'))}
alts = json.load(open(os.path.join(ROOT, 'tools', 'image_alt.json'), encoding='utf-8'))['images']

BRAND = 'sixosix magazine chicago'      # issue pages, the front page
SHORT = 'sixosix, chicago'               # article pages: the article's own words go first
HEAD_MAX, DESC_MAX = 55, 160
IMG = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*"([^"]+)"', re.I)

# --- image sizes, read from the files (JPEG, GIF, PNG) ------------------------------------
_sizes = {}
def size(src):
    """(width, height) of an /archive/... image, or None."""
    if src in _sizes:
        return _sizes[src]
    path = os.path.join(SITE, src[len('/archive/'):]) if src.startswith('/archive/') else None
    wh = None
    try:
        with open(path, 'rb') as fh:
            head = fh.read(26)
            if head[:6] in (b'GIF87a', b'GIF89a'):
                wh = struct.unpack('<HH', head[6:10])
            elif head[:8] == b'\x89PNG\r\n\x1a\n':
                wh = struct.unpack('>II', head[16:24])
            elif head[:2] == b'\xff\xd8':
                fh.seek(2)
                while True:
                    b = fh.read(1)
                    while b and b != b'\xff':
                        b = fh.read(1)
                    while b == b'\xff':
                        b = fh.read(1)
                    if not b:
                        break
                    marker = b[0]
                    if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                        continue
                    seglen = struct.unpack('>H', fh.read(2))[0]
                    if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack('>HH', fh.read(5)[1:5])
                        wh = (w, h)
                        break
                    fh.seek(seglen - 2, 1)
    except (OSError, TypeError, struct.error):
        wh = None
    _sizes[src] = wh
    return wh

# --- text helpers --------------------------------------------------------------------------
def alt_of(src):
    e = alts.get(src[len('/archive/'):]) if src.startswith('/archive/') else None
    return (e or {}).get('alt', ''), (e or {}).get('kind', '')

def images(page_html):
    return IMG.findall(page_html)

def tidy(s):
    """Whitespace collapsed, and none left before punctuation (where markup was stripped)."""
    s = re.sub(r'\s+', ' ', s).strip()
    return re.sub(r'\s+([,.;:!?])(?=\s|$|["”’)])', r'\1', s)

def lower_shouting(s):
    """'ST. PATRICK'S DAY — an amatuer's guide' -> 'st. patrick's day — an amatuer's guide'."""
    return ' — '.join(x.lower() if sum(c.isupper() for c in x) > 0.6 * max(1, sum(c.isalpha() for c in x)) else x
                      for x in s.split(' — '))

# parts of the 2004 pages that are no use in a snippet: navigation, page-source leftovers,
# copyright lines, and photo-shoot credit lists (which name private models)
JUNK = re.compile(r'(?i)^(untitled document|click to enlarge( photos?)?|see previous( photos?| photo essays?)?'
                  r'|back to (intro|top|side [ab] song \d+)|go to side [ab] song \d+|(next|previous|prev) movie'
                  r'|what to watch\W*|next|back|more)$')
SHOOT = re.compile(r'(?i)\b(models?|stylists?|styling|hair|make-?up|wardrobe|photographer|assistant|clothing|clothes'
                   r'|location)\s*[:/]')

def text_lines(page_html):
    h = re.sub(r'<(script|style)\b.*?</\1>', ' ', page_html, flags=re.S | re.I)
    h = re.sub(r'<br\s*/?>|</p>|</td>|</div>|</h\d>', '\n', h, flags=re.I)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', h))
    out = []
    for l in t.split('\n'):
        l = tidy(l)
        if (not l or len(re.sub(r'[\W\d_]+', '', l)) <= 2 or JUNK.match(l) or '©' in l or SHOOT.search(l)
                or re.fullmatch(r'(?i)(<<|>>|«|»|\||next|back|prev(ious)?|page|top|more|\d|\s)+(\s*(page|top|photo|photos))?', l)):
            continue
        out.append(lower_shouting(l))
    return out

def text_of(page_html):
    out = ''
    for l in text_lines(page_html):
        if out and out[-1] not in '.!?…:;"”’)' and len(out.rsplit('. ', 1)[-1]) <= 60:
            out += '.'
        out = (out + ' ' + l).strip()
    return out

def clip(s, n):
    s = tidy(s)
    if len(s) <= n:
        return s
    return s[:n - 1].rsplit(' ', 1)[0].rstrip(' ,;:—-') + '…'

def sentences(text, n=110):
    """The opening sentences of text, until there are about n characters."""
    out = ''
    for s in re.split(r'(?<=[.!?…"”])\s+', text):
        if out and len(out) >= n:
            break
        out = (out + ' ' + s).strip()
    return out

def joined(*parts):
    """Parts as sentences: 'a', 'b' -> 'a. b' (no doubled stops after ! or ?)."""
    out = ''
    for p in parts:
        p = tidy(p or '')
        if not p:
            continue
        if out:
            out += ('' if out[-1] in '.!?…' else '.') + ' '
        out += p
    return out

TITLES = ({a['title'].lower() for a in articles} | {(a.get('menuTitle') or '').lower() for a in articles}
          | {(a['section'] or '').lower() for a in articles}) - {''}

def clean_alt(alt, own_title=''):
    """Alt text fit for a snippet: no site watermarks or cover credits, no copyright line, and no
    leading caption naming another article ('by the way — yellow balloon animal' on another page)."""
    parts = [x for x in alt.split(' — ') if x.strip() and not re.search(r'606mag\.com|cover photo|©', x, re.I)
             and not re.match(r'(?i)sixosix issue \d+', x.strip())]
    if len(parts) > 1 and parts[0].strip().lower() in TITLES and parts[0].strip().lower() != own_title.lower():
        parts = parts[1:]
    return lower_shouting(tidy(' — '.join(parts)))

def display_name(a):
    """The article's name as its issue menu shows it (what readers click), unless the menu cut it
    short ('crap, scraps and...'); a redundant 'feature - ' prefix goes. Spelling variants of
    one name ('St Pats' / "st pat's") keep the one in the magazine's lowercase style."""
    menu, title = (a.get('menuTitle') or '').strip(), a['title'].strip()
    if not menu or menu.endswith(('...', '…')):
        name = title
    elif re.sub(r'\W', '', menu.lower()) == re.sub(r'\W', '', title.lower()):
        name = min(menu, title, key=lambda x: sum(c.isupper() for c in x))
    else:
        name = menu
    return re.sub(r'(?i)^(feature|fashion)\s+-\s+', '', name)

# --- credits -------------------------------------------------------------------------------
ROLE = (r'(?:words|text|story|interview|written|novella|photos?|photographs|photography|pictures|illustrations?'
        r'|illustrated|drawings|art|artwork|comics?|design|edited)')
ROLES = r'%s(?:\s*(?:,|and|&)\s*%s)*' % (ROLE, ROLE)
MARK = re.compile(r'(?i)(?:\b(?P<role>%s)\s*(?:\bby\b\s*:?|:)|(?P<bare>\bby\b\s*:?))\s*' % ROLES)
NOT_CREDIT = re.compile(r'(?i)\b(provided|courtesy|clothes|presented|sponsored|brought to you)\s*$')
NAME = re.compile(r"(?i)^[a-z][a-z.'’\- ]{1,40}$")
# one spelling per person (the magazine spelled some names several ways)
ALIAS = {'nick ziegler': 'nicholas ziegler', 'nick zeigler': 'nicholas ziegler', 'nicholas zeigler': 'nicholas ziegler',
         'stephanie mc niel': 'stephanie mcniel', 's. mc niel': 'stephanie mcniel', 's. mcniel': 'stephanie mcniel',
         's.mcniel': 'stephanie mcniel', 'bernie mc govern': 'bernie mcgovern', 'kami bremeyer': 'kami bremyer',
         'c. mladic': 'christine mladic', 'matt taplinger': 'matthew taplinger'}

def names_in(chunk):
    out = []
    for n in re.split(r'\s*(?:,|&|\band\b)\s*', chunk):
        n = re.sub(r'(?i)\s*606mag\.com\s*$', '', n).strip(" .,;:-—|")
        n = re.sub(r'\s+', ' ', n).lower()
        if (not n or re.search(r'\d|606mag|provided|courtesy', n) or not NAME.match(n) or len(n.split()) > 4
                or re.match(r'(the|a|an|way|now|all|me|you|us)\b', n) or len(n) < 3):
            continue
        out.append(ALIAS.get(n, n))
    return out

def credits_in(alt):
    """[(role, name)] from a byline like 'words by tom hardman — photos by douglas fogelson'."""
    out = []
    for seg in re.split(r'\s+[—|;]\s+', alt):
        marks = list(MARK.finditer(seg))
        for i, m in enumerate(marks):
            pre = seg[:m.start()]
            if NOT_CREDIT.search(pre):
                continue                               # "clothes provided by ..."
            role = (m.group('role') or '').lower()
            if not role and not m.group('bare').rstrip().endswith(':') and pre.strip():
                continue                               # a bare "by" inside a title needs "by:"
            end = marks[i + 1].start() if i + 1 < len(marks) else len(seg)
            role = re.sub(r'\bphoto\b', 'photos', re.sub(r'\s+', ' ', role)) or 'by'
            for n in names_in(seg[m.end():end]):
                if (role, n) not in out:
                    out.append((role, n))
    return out

def article_credits(a):
    """The article's credits, from its byline image (auth.gif) or its title lettering."""
    srcs = images(a['pages'][0]['html'])
    auth = [s for s in srcs if s.endswith('/auth.gif')]
    for s in auth + [s for s in srcs if s not in auth]:
        alt, kind = alt_of(s)
        if kind in ('text', 'mixed') and alt:
            found = credits_in(alt)
            if found:
                return found
    return []

def credit_phrase(role, names):
    return ('by ' if role == 'by' else role + ' by ') + ' and '.join(names)

def credit_line(creds, prefer=None):
    """'words by joe engels': the first credit (or the first of a preferred role), all its names."""
    if not creds:
        return ''
    role = next((r for r, _ in creds if prefer and prefer in r), creds[0][0])
    return credit_phrase(role, [n for r, n in creds if r == role])

def all_credits(creds):
    roles = []
    for r, _ in creds:
        if r not in roles:
            roles.append(r)
    return ', '.join(credit_phrase(r, [n for rr, n in creds if rr == r]) for r in roles)

def teaser(a):
    """The article's title lettering when it says more than the title (a dek)."""
    t = a['title'].lower()
    for s in images(a['pages'][0]['html'])[:8]:
        alt, kind = alt_of(s)
        if kind != 'text' or not alt or s.endswith('/auth.gif') or credits_in(alt) or '©' in alt:
            continue
        if not re.search(r'title|ttl|hdr|header|head', s.rsplit('/', 1)[1].lower()):
            continue
        alt = lower_shouting(clean_alt(alt, a['title']))
        if alt.lower().startswith(t + ' — '):
            alt = alt[len(t) + 3:]                     # 'MIX TAPE — iPod fieldnotes' -> 'iPod fieldnotes'
        if alt.lower().strip() == t or len(alt) < 12 or 'sixosix' in alt.lower() or re.search(r'\bby\b', alt.lower()):
            continue
        return alt
    return ''

# --- pictures ------------------------------------------------------------------------------
def photos(srcs, min_side):
    """(src, (w, h), alt) for the page's photos at least min_side on both sides, largest first."""
    out = []
    for s in srcs:
        alt, kind = alt_of(s)
        wh = size(s) if kind in ('photo', 'mixed') else None
        if wh and min(wh) >= min_side:
            out.append((s, wh, alt))
    return sorted(out, key=lambda x: -x[1][0] * x[1][1])

def preview(srcs):
    """The link-preview picture: the page's largest photo, if big enough for Facebook (200px)."""
    p = photos(srcs, 200)
    return p[0] if p else None

def main_photo(srcs):
    """The photo a photo page is about (its largest, any reasonable size)."""
    p = photos(srcs, 60)
    return p[0] if p else None

# --- sub-page names ------------------------------------------------------------------------
def path_label(path):
    """A readable name from the address alone: '2/' -> 'page 2', 'a3/' (mix tape) -> 'side a, song 3'."""
    p = path.strip('/')
    if re.fullmatch(r'\d+', p):
        return 'page ' + p
    m = re.fullmatch(r'([ab])(\d+)', p)
    if m:
        return 'side %s, song %s' % (m[1], m[2])
    if p in ('pos', 'neg'):
        return {'pos': 'for', 'neg': 'against'}[p]
    if re.fullmatch(r'[a-z]', p) or re.fullmatch(r'choice-(\d+|untitled)', p):
        return ('choice ' + p.split('-')[-1]).replace(' untitled', '').strip()
    return ', '.join(('page ' + x) if x.isdigit() else re.sub(r'-+', ' ', x.replace('untitled', '')).strip()
                     for x in p.split('/') if x.replace('untitled', '').strip('-'))

def own_label(a, p, first_srcs):
    """A sub-page's own name: the item it marks as current (movies: '2x.gif' is the film shown),
    its own lettering (not the article's), or the mix tape's side and song."""
    srcs = images(p['html'])
    for s in srcs:
        alt, kind = alt_of(s)
        m = re.search(r'(?i)side\s+([ab])\s*-\s*song\s+(\d+)', alt)
        if m:
            return 'side %s, song %s' % (m[1].lower(), m[2])
    for s in srcs:
        if re.search(r'(?i)(\dx|_tx|\d_t)\.(gif|jpe?g)$', s):
            alt = alt_of(s)[0] or alt_of(re.sub(r'(?i)x(\.\w+)$', r'\1', s))[0]
            if alt and len(alt) <= 45:
                return lower_shouting(clean_alt(alt)).lower()
    for s in srcs[:8]:
        if s in first_srcs:
            continue
        alt, kind = alt_of(s)
        if kind not in ('text', 'mixed') or not alt or credits_in(alt) or 'sixosix' in alt.lower():
            continue
        own = clean_alt(alt.split(' — ')[0], a['title'])
        if own and own.lower() != a['title'].lower() and len(own) <= 40 and not re.fullmatch(r'(?i)(next|back|photo \d+|page \d+)', own):
            return lower_shouting(own).replace(' | ', ' / ')
    return ''

# --- build ---------------------------------------------------------------------------------
pages, arts, canonical = {}, {}, {}
site_photo = None

# each issue's picture for pages that have none: its cover photo, or the issue's largest article photo
issue_pic = {}
for n, issue in issues.items():
    pic = preview(images(issue['coverHtml']))
    if not pic:
        cands = [x for a in articles if a['issue'] == n for x in photos(images(a['pages'][0]['html']), 300)]
        pic = max(cands, key=lambda x: x[1][0] * x[1][1]) if cands else None
    issue_pic[n] = pic

# copies: the first page with the same markup (or, for photo pages, the same photo) is the original
first_by_html, built = {}, [a for a in sorted(articles, key=lambda a: a['id']) if a['issue'] in issues]
for a in built:
    seen_photo = {}
    for p in a['pages']:
        key = re.sub(r'\s+', ' ', p['html']).strip()
        if key in first_by_html:
            canonical[p['url']] = first_by_html[key]
            continue
        first_by_html[key] = p['url']
        if 'img-' in p['path']:
            mp = main_photo(images(p['html']))
            if mp and mp[0] in seen_photo:
                canonical[p['url']] = seen_photo[mp[0]]
            elif mp:
                seen_photo[mp[0]] = p['url']

for a in built:
    issue = issues[a['issue']]
    month = issue['month'].lower()
    a = dict(a, title=display_name(a))            # the menu's name throughout (titles, labels)
    creds = article_credits(a)
    dek = teaser(a)
    first_srcs = set(images(a['pages'][0]['html']))
    first_pic = preview(images(a['pages'][0]['html'])) or issue_pic[a['issue']]
    first_body = text_of(a['pages'][0]['html'])
    summary = joined(dek, sentences(first_body) if len(first_body) > 60 else '')
    arts[a['id']] = {'name': a['title'], 'credits': [{'role': r, 'name': n} for r, n in creds], 'teaser': dek,
                     'summary': clip(summary, 120) if len(summary) >= 40 else ''}
    # photo pages numbered by the photo they show
    order = []
    for p in a['pages']:
        if 'img-' in p['path']:
            mp = main_photo(images(p['html']))
            key = mp[0] if mp else p['url']
            if key not in order:
                order.append(key)
    for p in a['pages']:
        srcs = images(p['html'])
        pic = preview(srcs) or first_pic
        body = text_of(p['html'])
        snippet = sentences(body) if len(body) > 60 else ''
        if p['path'] == '':
            name = a['title']
            cred = credit_line(creds)
            head = name + (', ' + cred if cred and len(name) + 2 + len(cred) <= HEAD_MAX else '')
            if len(joined(dek, snippet)) >= 60:
                desc = joined(dek, snippet)
            else:
                shown = main_photo(srcs)
                desc = joined(dek, snippet, clean_alt(shown[2], a['title']) if shown else '',
                              '%s%s, sixosix magazine, %s.' % (a['title'], ', ' + all_credits(creds) if creds else '', month))
        elif 'img-' in p['path']:
            mp = main_photo(srcs)
            k = order.index(mp[0] if mp else p['url']) + 1
            label = 'photo %d of %d' % (k, len(order)) if len(order) > 1 else 'photo'
            name = '%s, %s' % (a['title'], label)
            head = name
            pcred = credit_line(creds, 'photo')
            desc = joined(clean_alt(mp[2], a['title']) if mp else '',
                          '%s from %s%s, sixosix magazine, %s.' % (label, a['title'], ', ' + pcred if pcred else '', month))
        else:
            label = own_label(a, p, first_srcs)
            if not label or p['path'].strip('/').isdigit() or len(a['title']) + 2 + len(label) > HEAD_MAX:
                label = path_label(p['path'])
            name = '%s, %s' % (a['title'], label)
            head = name
            shown = main_photo(srcs)
            where = '%s, %s, sixosix magazine, %s.' % (a['title'], label, month)
            desc = snippet if len(snippet) >= 60 else joined(snippet, clean_alt(shown[2], a['title']) if shown else '', where)
        rec = {'name': clip(name, 90), 'title': clip(head, HEAD_MAX) + ' | %s, %s' % (SHORT, month),
               'description': clip(desc, DESC_MAX)}
        if p['url'] in canonical:
            rec['canonical'] = canonical[p['url']]
        if pic:
            rec.update(image=pic[0], imageWidth=pic[1][0], imageHeight=pic[1][1], imageAlt=clean_alt(pic[2]))
        pages[p['url']] = rec

for n, issue in issues.items():
    month = issue['month'].lower()
    names = []
    for sec in issue.get('sections', []):
        for aid in sec.get('articles', []):
            a = next((x for x in articles if x['id'] == aid), None)
            if a and display_name(a) not in names:
                names.append(display_name(a))
    rec = {'name': 'issue %d: %s' % (n, issue['name']),
           'title': 'issue %d: %s | %s, %s' % (n, issue['name'], BRAND, month),
           'description': clip('issue %d of sixosix, a chicago web magazine, %s. in this issue: %s.' % (n, month, ', '.join(names)), DESC_MAX)}
    pic = issue_pic[n]
    if pic:
        rec.update(image=pic[0], imageWidth=pic[1][0], imageHeight=pic[1][1], imageAlt=clean_alt(pic[2]))
    pages[issue['url']] = rec

# the front page's picture: the widest issue picture
front = max((pages[i['url']] for i in issues.values() if 'image' in pages[i['url']]), key=lambda r: r['imageWidth'])
pages['/'] = {
    'name': 'sixosix magazine',
    'title': 'sixosix magazine chicago, 2004 | 606mag.com',
    'description': 'sixosix (606mag.com) was a monthly chicago web magazine of art, music, nightlife, photo essays '
                   'and humor. all twelve 2004 issues, kept as they were published.',
    **{k: front[k] for k in ('image', 'imageWidth', 'imageHeight', 'imageAlt')},
}
pages['/about/'] = {
    'name': 'about this archive',
    'title': 'about this archive | %s | 606mag.com' % BRAND,
    'description': '606mag.com is the archive of sixosix, a chicago web magazine published monthly in 2004, restored '
                   'in 2026 from the wayback machine and the magazine\'s own database.',
    **{k: front[k] for k in ('image', 'imageWidth', 'imageHeight', 'imageAlt')},
}
pages['/articles/'] = {
    'name': 'all articles',
    'title': 'all articles, issue by issue | %s | 606mag.com' % BRAND,
    'description': 'every article from the twelve 2004 issues of sixosix, a chicago web magazine, with its writers '
                   'and photographers: features, photo essays, regulars and more.',
    **{k: front[k] for k in ('image', 'imageWidth', 'imageHeight', 'imageAlt')},
}
pages['/privacy/'] = {
    'name': 'privacy policy',
    'title': 'privacy policy | %s | 606mag.com' % BRAND,
    'description': 'how 606mag.com handles visitor statistics, advertising cookies and the reader comments kept from 2004.',
}

# 30 under 30 (the most-read article): the people it profiled, as the caption images print them
# (two names fixed where the magazine's own index and captions disagree: Achatz, Alvarado-Rivera
# is already right in the captions), and each page names the people on it, so a search for one
# of them finds their page
FIX = {'Grant Ashatz': 'Grant Achatz'}
people = []
for i in range(1, 31):
    m = re.match(r'(.+?)\s+(\d+)\s+(.+)$', alt_of('/archive/issues/wigu/under30/images/30_%02d_t.gif' % i)[0])
    if m:
        people.append({'name': FIX.get(m[1], m[1]), 'age': int(m[2]), 'jobTitle': m[3]})
by_name = {x['name']: x for x in people}
for a in built:
    if a['id'] != 68:
        continue
    month = issues[a['issue']]['month'].lower()
    for p in a['pages']:
        here = []
        for s in images(p['html']):
            m = re.search(r'/30_(\d\d)_t\.gif$', s)
            mm = re.match(r'(.+?)\s+\d+\s+', alt_of(s)[0]) if m else None
            if mm and FIX.get(mm[1], mm[1]) in by_name:
                here.append(by_name[FIX.get(mm[1], mm[1])])
        if not here:
            continue
        shown, rest = [], [x['name'] for x in here]
        while rest and len('30 under 30: ' + ', '.join(shown + rest[:1]) + ' and more') <= 66:
            shown.append(rest.pop(0))
        head = '30 under 30: ' + ', '.join(shown) + (' and more' if rest else '')
        rec = pages[p['url']]
        rec['name'], rec['title'] = head, head + ' | %s, %s' % (SHORT, month)
        if p['path'] == '':
            rec['description'] = clip('thirty under thirty, the new chicago: thirty chicagoans profiled in april 2004, among them '
                                      'Grant Achatz, Alpana Singh, Eboo Patel, Rachel Barton, DaMarcus Beasley, Jessica Hopper '
                                      'and Sho Yano.', DESC_MAX)
        else:
            rec['description'] = clip('30 under 30: ' + '; '.join('%s, %d, %s' % (x['name'], x['age'], x['jobTitle']) for x in here) + '.', DESC_MAX)

# --- photo alt text in context ---------------------------------------------------------------
# Each article's photos say which article they're from and who made them; the lead photo also
# says what the article is about. The description of the picture itself follows ("photo: ...").
def as_tail(alt):
    alt = clean_alt(alt)
    return alt[:1].lower() + alt[1:] if alt[:1].isupper() and not alt[:2].isupper() else alt

context = {}
for a in built:
    if a['url'] in canonical:
        continue                                   # an article published twice: its first copy speaks
    info = arts[a['id']]
    name, creds, summary = info['name'], [(c['role'], c['name']) for c in info['credits']], info['summary']
    folder = 'issues/%s/%s/' % (a['issueFolder'], a['folder'])
    lead = main_photo(images(a['pages'][0]['html']))
    lead_key = lead[0][len('/archive/'):] if lead else None
    order = []
    for p in a['pages']:
        if 'img-' in p['path']:
            mp = main_photo(images(p['html']))
            if mp and mp[0] not in order:
                order.append(mp[0])
    for p in a['pages']:
        for src in images(p['html']):
            key = src[len('/archive/'):] if src.startswith('/archive/') else None
            if not key or not key.startswith(folder) or key in context:
                continue
            alt, kind = alt_of(src)
            if kind not in ('photo', 'mixed') or not alt:
                continue
            word = 'photo' if kind == 'photo' else 'picture'
            if key == lead_key:
                head = name + (', ' + all_credits(creds) if creds else '')
                text = joined(head + (': ' + summary if summary else ''), '%s: %s' % (word, as_tail(alt)))
            else:
                where = name + (', photo %d of %d' % (order.index(src) + 1, len(order)) if src in order and len(order) > 1 else '')
                pcred = credit_line(creds, 'photo')
                text = '%s%s: %s' % (where, ', ' + pcred if pcred else '', as_tail(alt))
            context[key] = clip(text, 280)

# 30 under 30: each portrait names its person, as its caption image does
for i, person in enumerate(people, 1):
    key = 'issues/wigu/under30/images/30_%02d.gif' % i
    alt = alt_of('/archive/' + key)[0]
    if alt:
        context[key] = clip('30 under 30: %s, %d, %s, april 2004. photo: %s' % (person['name'], person['age'], person['jobTitle'], as_tail(alt)), 280)

# issue covers: a picture that links to an article says which one
LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
by_url = {a['url']: a for a in built}
for n, issue in issues.items():
    for href, inner in LINK.findall(issue['coverHtml']):
        a = by_url.get(canonical.get(href, href))
        if not a:
            continue
        info = arts[a['id']]
        head = info['name'] + (', ' + credit_line([(c['role'], c['name']) for c in info['credits']]) if info['credits'] else '')
        for src in images(inner):
            key = src[len('/archive/'):] if src.startswith('/archive/') else None
            alt, kind = alt_of(src)
            if key and kind in ('photo', 'mixed') and alt and key not in context:
                context[key] = clip('%s: %s' % (head, as_tail(alt)), 280)

# link previews describe their picture the same way
for rec in pages.values():
    k = rec.get('image', '')[len('/archive/'):]
    if k in context:
        rec['imageAlt'] = context[k]

# every page that is no copy has its own title: a clash gets a readable qualifier, never an address
seen = {}
for url, rec in pages.items():
    if 'canonical' not in rec:
        seen.setdefault(rec['title'], []).append(url)
for t, urls in seen.items():
    for k, url in enumerate(urls[1:], 2):
        pages[url]['title'] = t.replace(' | ', ' (%d) | ' % k, 1)
        pages[url]['name'] += ' (%d)' % k

out = {'_about': 'Generated by tools/make_seo.py; read by web/src/lib/seo.ts. Search titles, descriptions, '
                 'link-preview images and canonical copies per page, credits per article. Edit the script, not this file.',
       'pages': dict(sorted(pages.items())), 'articles': {str(k): v for k, v in sorted(arts.items())},
       'people': {'68': people}}
with open(os.path.join(DATA, 'seo.json'), 'w', encoding='utf-8') as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
    fh.write('\n')

with open(os.path.join(ROOT, 'tools', 'image_alt_context.json'), 'w', encoding='utf-8') as fh:
    json.dump({'_about': 'Generated by tools/make_seo.py: alt text for the articles\' photos with their article, credits '
                         'and (lead photo) summary, ahead of the picture\'s description from tools/image_alt.json. '
                         'Used by tools/apply_alt_text.py and tools/make_sitemap.py. Edit the script, not this file.',
               'images': dict(sorted(context.items()))}, fh, indent=1, ensure_ascii=False)
    fh.write('\n')
print('photo alt text in context: %d photos' % len(context))

own = [r['title'] for r in pages.values() if 'canonical' not in r]
print('seo: %d pages (%d copies pointing at their original), %d distinct titles, %d with a picture, '
      '%d articles with credits, %d people in 30 under 30'
      % (len(pages), len(canonical), len(set(own)), sum('image' in r for r in pages.values()),
         sum(bool(v['credits']) for v in arts.values()), len(people)))
if len(set(own)) != len(own):
    sys.exit('make_seo: titles still repeat')
