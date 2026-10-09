#!/usr/bin/env python3
"""Reconstruct the magazine's catalog (the lost `issues` / `article_list` tables) from
the recovered pages: issue number -> folder, color, sections -> articles, and for
each article its folder, title, pages, and which raw sources hold its text.

Usage: catalog.py ARCHIVE_DIR SERVER_ROOT OUT_JSON
"""
import html, json, os, re, sys
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, urlparse

arc, server_root, out_path = sys.argv[1:4]
index = json.load(open(os.path.join(arc, '_index.json')))

def doc(info):
    return open(os.path.join(arc, '_blobs', info['digest']), 'rb').read().decode('cp1252', 'replace')

def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s))).strip()

SIDEBAR = re.compile(r'class="submenu_maincell">(.*?)(?:new comments|</td>\s*<td valign="top" width="682")', re.S)
HEADING = re.compile(r'<span class="submenu_title"[^>]*>(.*?)</span>', re.S)
LINK = re.compile(r'<a\b[^>]*href="main\.php\?id=(\d+)[^"]*"[^>]*>(.*?)</a>', re.S)
CHIP = re.compile(r'background-color:(#[0-9A-Fa-f]{6});"><a href="main\.php\?issue_id=(\d+)"')
ARTICLE_CSS = re.compile(r'<link href="/?issues/([\w-]+)/([^/"]+)/local\.css"', re.I)
ISSUE_CSS = re.compile(r'<link href="/?issues/([\w-]+)/local\.css"', re.I)
IMG_DIR = re.compile(r'(?:src|background)="/?issues/([\w-]+)/([^/"]+)/images/', re.I)

def sidebar(d):
    m = SIDEBAR.search(d)
    if not m:
        return None, []
    block, sections, current, number = m.group(1), [], None, None
    for tok in re.finditer(r'<span class="submenu_title"[^>]*>(.*?)</span>|<a\b[^>]*href="main\.php\?id=(\d+)[^"]*"[^>]*>(.*?)</a>', block, re.S):
        if tok.group(1) is not None:
            title = clean(tok.group(1))
            if re.match(r'issue\s+\d+', title, re.I):
                number = int(title.split()[-1])
                current = {'section': 'issue', 'articles': []}
            else:
                current = {'section': title, 'articles': []}
            sections.append(current)
        elif current is not None:
            current['articles'].append({'id': int(tok.group(2)), 'title': clean(tok.group(3))})
    return number, [s for s in sections if s['articles']]

issues, colors = {}, {}
articles = defaultdict(lambda: {'pages': set()})
for ident, info in index.items():
    if info.get('status') != 'done' or not ident.startswith('/main.php'):
        continue
    q = dict(parse_qsl(urlparse(ident).query))
    d = doc(info)
    for color, n in CHIP.findall(d):
        colors.setdefault(int(n), color)
    number, sections = sidebar(d)
    css_issue = ISSUE_CSS.search(d)
    if 'issue_id' in q and q['issue_id'].isdigit() and css_issue:
        n = int(q['issue_id'])
        issues.setdefault(n, {'number': n, 'folder': css_issue.group(1), 'heading': number,
                              'sections': sections, 'source_ts': info['ts']})
    if 'id' in q and q['id'].isdigit():
        a = articles[int(q['id'])]
        a['pages'].add(q.get('page', 'index'))
        m = ARTICLE_CSS.search(d)
        folders = Counter(IMG_DIR.findall(d))
        if m:
            a.setdefault('issue_folder', m.group(1)); a.setdefault('folder', m.group(2))
        elif folders:
            (f_issue, f_dir), _ = folders.most_common(1)[0]
            if f_dir not in ('index', 'images'):
                a.setdefault('issue_folder', f_issue); a.setdefault('folder', f_dir)
        t = re.search(r'<title>(.*?)</title>', d, re.S | re.I)
        if t and ('&bull;' in t.group(1) or '•' in t.group(1)):
            parts = re.split(r'&bull;|•', t.group(1))
            if len(parts) > 3:
                a.setdefault('page_title', clean(parts[-1]))
        for sec in sections:
            if any(x['id'] == int(q['id']) for x in sec['articles']):
                a.setdefault('section', sec['section'])

# menu titles + sections from the issue pages
for iss in issues.values():
    for s in iss['sections']:
        for x in s['articles']:
            a = articles[x['id']]
            a.setdefault('menu_title', x['title'])
            a['issue_number'] = iss['number']; a.setdefault('section', s['section'])
            a.setdefault('issue_folder', iss['folder'])

# an article's issue follows from its folder
folder_issue = {i['folder']: n for n, i in issues.items()}
for a in articles.values():
    if a.get('issue_folder') in folder_issue:
        a['issue_number'] = folder_issue[a['issue_folder']]
    elif a.get('issue_folder') == 'general':
        a['issue_number'] = 0

# raw sources for each article's text
def server_pages(issue_folder, folder):
    d = os.path.join(server_root, 'issues', issue_folder, folder)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if re.fullmatch(r'index\d*\.(php|html?)', f))
cc_dirs = {k.rstrip('/') for k, v in index.items() if v.get('source') == 'cc' and k.startswith('/issues/')}
out_articles = {}
for aid, a in sorted(articles.items()):
    rec = {k: (sorted(v) if isinstance(v, set) else v) for k, v in a.items()}
    if a.get('issue_folder') and a.get('folder'):
        rec['server_files'] = server_pages(a['issue_folder'], a['folder'])
        rec['common_crawl_fragment'] = '/issues/%s/%s' % (a['issue_folder'], a['folder']) in cc_dirs
    out_articles[aid] = rec
for n, c in colors.items():
    if n in issues:
        issues[n]['color'] = c
json.dump({'issues': {k: issues[k] for k in sorted(issues)}, 'articles': out_articles},
          open(out_path, 'w'), indent=1)

print('issues reconstructed: %d of 12' % len(issues))
for n in sorted(issues):
    i = issues[n]
    count = sum(len(s['articles']) for s in i['sections'])
    print('  issue %2d  %-12s %s  %2d articles  sections: %s' % (
        n, i['folder'], i.get('color', '?'), count, ', '.join(s['section'] for s in i['sections'])))
known = [a for a in out_articles.values() if a.get('folder')]
print('articles: %d ids seen, %d with folder known, %d with an issue/section' % (
    len(out_articles), len(known), sum(1 for a in out_articles.values() if a.get('issue_number'))))
print('  text sources: server files for %d, Common Crawl fragment for %d' % (
    sum(1 for a in known if a.get('server_files')), sum(1 for a in known if a.get('common_crawl_fragment'))))
