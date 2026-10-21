#!/usr/bin/env python3
"""Give the archive pages (/archive: the original 2004 pages CI copies into the build) the
rebuilt site's Google tags, and point archive copies of rebuilt pages at the rebuilt address.

- Tags: the block web/src/components/HeadTags.astro fences with <!--606:tags--> in
  DIST/index.html (absent while web/src/config.ts is empty), copied byte for byte.
- <link rel="canonical"> on archive pages whose content has a rebuilt page (an article view
  or issue cover, from DIST/redirects.json, and the bare article and cover bodies the 2004 pages
  included: issues/<issue>/<article>/index.html), so search engines treat the rebuilt one as primary.
- <meta name="robots" content="noindex,follow"> on pages that are no use as search results: the
  readers' Sad Libs results (main/...adj1-...), the photo popups (popup/) and the bare bodies of
  the 2004 section pages (issues/general/*/index.html; their full pages are main/general-*.html). They stay online; robots.txt doesn't block them.
- <html lang="en"> where the 2004 page had no language (it changes nothing on screen).
- The RSS feed (rss.xml, behind every page's RSS button) links its items to the rebuilt
  articles instead of the dead 2004 main.php?id=N addresses.
- The footer's "privacy policy" link opens the current policy (/privacy/), as on the rebuilt
  pages, and the 2004 policy page says that it is kept as a historical document.

Both go right after <head> (or a leading <!doctype html><meta charset>); fragments without a
head are skipped. Anything a previous run added is replaced, so running twice changes nothing.
Line endings are kept (510 archive pages use CRLF). Only for a build output, never for site/.

Usage: inject_archive_tags.py DIST_DIR SITE_URL
"""
import json, os, posixpath, re, sys
from urllib.parse import parse_qsl, urlencode, urlparse

dist, site_url = sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/')
archive = os.path.join(dist, 'archive')
repo_site = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site'))
if os.path.islink(archive) or os.path.realpath(archive) == repo_site:
    sys.exit('inject_archive_tags: %s is (a link to) site/ itself; run it on a build copy only' % archive)

FENCE = re.compile(r'<!--606:(tags|canonical|robots|note)-->.*?<!--/606:\1-->', re.S)
HTML_TAG = re.compile(r'<html\b(?![^>]*\blang\s*=)', re.I)
NOINDEX = re.compile(r'^(main/[^/]*adj1-[^/]*|popup/[^/]*)\.html$')      # Sad Libs results (some named for the reader), popups
OLD_POLICY = 'main/general-footer_page-privacy.html'
OLD_POLICY_LINK = re.compile(r'href="([^"]*general-footer_page-privacy\.html)"')
NOTE_AT = '<span class="style6">privacy policy</span><br>'
NOTE = ('<!--606:note--><br><b>This is the magazine\'s 2004 privacy policy, kept as a historical document; it no '
        'longer applies. The current policy is at <a href="../../privacy/">606mag.com/privacy</a>.</b><br><!--/606:note-->')
HEAD = re.compile(r'<head\b[^>]*>(?:\s*<meta charset="utf-8">)?|^<!doctype html>\s*(?:<html lang="en">)?\s*<meta charset="utf-8">', re.I)

home = open(os.path.join(dist, 'index.html'), encoding='utf-8').read()
tags = re.search(r'<!--606:tags-->.*?<!--/606:tags-->', home, re.S)
tags = tags.group(0) if tags else ''

# archive file -> rebuilt address, from the old-link map (only where every old address agrees)
redirects = json.load(open(os.path.join(dist, 'redirects.json')))
targets = {}
for old, file in redirects['archive'].items():
    u = urlparse(old)
    if u.path not in ('/', '/main.php', '/index.php'):
        continue
    q = parse_qsl(u.query, keep_blank_values=True)
    d = dict(q)
    target = None
    a = redirects['articles'].get(d.get('id', ''))
    if a:
        key = urlencode(sorted((k, v) for k, v in q if k != 'id' and not (k == 'page' and v in ('index', ''))))
        if key in a['pages']:
            target = a['base'] + a['pages'][key]
        elif not a['pages'] and key == '':
            target = a['base']                # an issue's contents page: the rebuilt cover
    elif set(d) == {'issue_id'} and d['issue_id'] in redirects['issues']:
        target = redirects['issues'][d['issue_id']]
    if target is not None:
        targets.setdefault(file, set()).add(target)
canonical = {f: site_url + '/' + t.pop() for f, t in targets.items() if len(t) == 1}

# the bare bodies the 2004 pages included (issues/<issue folder>/<article folder>/index.html, and
# issues/<issue folder>/index/index.html for covers): the rebuilt article or cover where there is one
data = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web', 'src', 'data')
issue_list = json.load(open(os.path.join(data, 'issues.json'), encoding='utf-8'))
built = {i['number'] for i in issue_list}
bodies = {}
for a in sorted(json.load(open(os.path.join(data, 'articles.json'), encoding='utf-8')), key=lambda a: a['id']):
    if a['issue'] in built:          # an article published twice: its first copy (as tools/make_seo.py)
        bodies.setdefault('issues/%s/%s/index.html' % (a['issueFolder'], a['folder']), a['url'])
for i in issue_list:
    bodies.setdefault('issues/%s/index/index.html' % i['folder'], i['url'])
for f, url in bodies.items():
    canonical.setdefault(f, site_url + url)
# bodies of the 2004 site's own section pages, whose full page is archive/main/general-*.html
GENERAL_BODY = re.compile(r'^issues/general/[^/]+/index\.html$')

tagged = linked = hidden = skipped = changed = 0
for dp, dirs, files in os.walk(archive):
    dirs.sort()
    for name in sorted(files):
        if not name.endswith('.html'):
            continue
        path = os.path.join(dp, name)
        rel = os.path.relpath(path, archive).replace(os.sep, '/')
        with open(path, encoding='utf-8', newline='') as fh:
            doc = fh.read()
        new = FENCE.sub('', doc)
        m = HEAD.search(new)
        if not m:
            skipped += 1                      # an include fragment, not a page anyone visits
            continue
        add = tags
        if rel in canonical:
            add += '<!--606:canonical--><link rel="canonical" href="%s"><!--/606:canonical-->' % canonical[rel]
            linked += 1
        elif NOINDEX.match(rel) or GENERAL_BODY.match(rel):
            add += '<!--606:robots--><meta name="robots" content="noindex,follow"><!--/606:robots-->'
            hidden += 1
        if tags:
            tagged += 1
        new = new[:m.end()] + add + new[m.end():]
        first = re.search(r'<html\b[^>]*>', new, re.I)      # the page's own tag, not any later copy
        if first and HTML_TAG.match(new, first.start()):
            new = new[:first.start()] + '<html lang="en"' + new[first.start() + 5:]
        elif not first and re.match(r'<!doctype html>', new, re.I):  # pages generated without an <html> tag
            new = new[:15] + '<html lang="en">' + new[15:]
        if rel == OLD_POLICY:
            if new.count(NOTE_AT) != 1:
                sys.exit('inject_archive_tags: %s changed; place the 2004-policy note by hand' % rel)
            new = new.replace(NOTE_AT, NOTE_AT + NOTE)
        else:                                 # footer links to the 2004 policy open the current one
            here = posixpath.dirname('archive/' + rel)
            to_privacy = posixpath.relpath('privacy', here) + '/'
            new = OLD_POLICY_LINK.sub(lambda l: 'href="%s"' % to_privacy
                                      if posixpath.normpath(posixpath.join(here, l.group(1))) == 'archive/' + OLD_POLICY
                                      else l.group(0), new)
        if new != doc:
            with open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(new)
            changed += 1
# the RSS feed: its items (main.php?id=N on the old domain) open the rebuilt articles
feed_path, fixed = os.path.join(archive, 'rss.xml'), 0
if os.path.exists(feed_path):
    with open(feed_path, encoding='utf-8', newline='') as fh:
        feed = fh.read()
    def item_link(m):
        a = redirects['articles'].get(m.group(1))
        return '<link>%s/%s</link>' % (site_url, a['base']) if a else m.group(0)
    new = re.sub(r'<link>https?://(?:www\.)?606mag\.com/main\.php\?id=(\d+)</link>', item_link, feed)
    new = re.sub(r'<link>https?://(?:www\.)?606mag\.com/?</link>', '<link>%s/</link>' % site_url, new)
    fixed = len(re.findall(r'<link>%s/' % re.escape(site_url), new))
    if new != feed:
        with open(feed_path, 'w', encoding='utf-8', newline='') as fh:
            fh.write(new)
        changed += 1
print('rss.xml: %d links open the rebuilt site' % fixed)
print('archive pages: %d with the Google tags, %d with a canonical link, %d not for search results, '
      '%d fragments skipped, %d files changed' % (tagged, linked, hidden, skipped, changed))
