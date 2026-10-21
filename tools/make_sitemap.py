#!/usr/bin/env python3
"""Write DIST/sitemap.xml for search engines: every page of the build (rebuilt and archive)
except the old-link pages (404 and the /main.php/-style redirects), the "not archived" notice,
include fragments, and archive pages that name a rebuilt page as canonical or ask not to be
indexed (tools/inject_archive_tags.py). Each page also lists its photos (images
tools/image_alt.json describes as photos or pictures with words) with their descriptions as
title and caption (the articles' photos in context: tools/image_alt_context.json), so they can
appear in image search.

<lastmod> is the date the pages last really changed (LASTMOD below: the 2026 restoration,
when every page got its search tags and the "about this archive" link), never the build date;
change it only when the pages themselves change. <priority> ranks the front page, the issues
and the about page above articles, articles above their sub-pages, and the 2004 archive last.
Run before relativize_dist.py (rebuilt pages still use /archive/... paths).

Usage: make_sitemap.py DIST_DIR SITE_URL
"""
import json, os, posixpath, re, sys
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

dist, site_url = sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/')
SKIP = {'404.html', 'archive/_missing.html'}
LASTMOD = '2026-10-21'          # the last real change to the pages (see above)
NOINDEX = re.compile(r'<meta\s+name="robots"\s+content="noindex', re.I)
CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"', re.I)
OLD_LINK = re.compile(r'^(main|index|index\.v\d+)\.php/index\.html$')      # pages/[old]: redirects only
PAGE = re.compile(r'<head\b|^<!doctype html', re.I)
IMG_SRC = re.compile(r'''<img\b[^>]*?\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''', re.I)
HERE = os.path.dirname(os.path.abspath(__file__))
alt_map = json.load(open(os.path.join(HERE, 'image_alt.json'), encoding='utf-8'))['images']
# the articles' photos in context (tools/make_seo.py): their article, credits and summary
context = json.load(open(os.path.join(HERE, 'image_alt_context.json'), encoding='utf-8'))['images']

def priority(path):
    if path == '':
        return '1.0'
    if path in ('about/', 'articles/') or re.fullmatch(r'issues/\d+/', path):
        return '0.8'
    if re.fullmatch(r'issues/\d+/[^/]+/', path):
        return '0.6'
    if path.startswith('issues/'):
        return '0.4'
    return '0.2' if path == 'privacy/' else '0.3'

def image_entry(url, alt):
    """<image:image> with the photo's description as caption, and as title its article and
    credits (photos in context, "speed dating, words by ...: ...") or its first part."""
    alt = re.sub(r'\s+', ' ', alt).strip()
    title = (alt.split(': ')[0] if ': ' in alt[:120] else alt.split(' — ')[0])[:100]
    return ('<image:image><image:loc>%s</image:loc>' % escape(url)
            + ('<image:title>%s</image:title><image:caption>%s</image:caption>' % (escape(title), escape(alt)) if alt else '')
            + '</image:image>')

def photos(doc, page_dir):
    """Archive paths of the photos a page shows, in order, once each."""
    seen = []
    for m in IMG_SRC.finditer(doc):
        src = unquote(next(g for g in m.groups() if g is not None).split('?')[0])
        if src.startswith('/archive/'):
            p = src[len('/archive/'):]
        elif not src.startswith(('/', 'http:', 'https:', 'data:')) and page_dir.startswith('archive'):
            p = posixpath.normpath(posixpath.join(page_dir, src))
            p = p[len('archive/'):] if p.startswith('archive/') else None
        else:
            p = None
        if p and alt_map.get(p, {}).get('kind') in ('photo', 'mixed') and p not in seen:
            seen.append(p)
    return seen[:1000]
urls = []
for dp, dirs, files in os.walk(dist):
    dirs.sort()
    for name in sorted(files):
        if not name.endswith('.html'):
            continue
        rel = os.path.relpath(os.path.join(dp, name), dist).replace(os.sep, '/')
        if rel in SKIP:
            continue
        doc = open(os.path.join(dp, name), encoding='utf-8', errors='replace').read()
        head = doc[:6000]
        path = rel[:-len('index.html')] if name == 'index.html' else rel
        canon = CANONICAL.search(head)
        if (not PAGE.search(head) or NOINDEX.search(head) or OLD_LINK.match(rel)
                or (canon and canon.group(1) != site_url + '/' + path)):      # a copy of another page
            continue
        urls.append((site_url + '/' + quote(path), [site_url + '/archive/' + quote(p) for p in photos(doc, posixpath.dirname(rel))]))
if len(urls) > 50000:
    sys.exit('make_sitemap: %d addresses is over the 50,000 a sitemap may hold' % len(urls))
with open(os.path.join(dist, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
             ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n')
    fh.writelines('<url><loc>%s</loc><lastmod>%s</lastmod><changefreq>yearly</changefreq><priority>%s</priority>%s</url>\n'
                  % (escape(u), LASTMOD, priority(u[len(site_url) + 1:]),
                     ''.join(image_entry(i, context.get(unquote(i[len(site_url + '/archive/'):])) or alt_map.get(unquote(i[len(site_url + '/archive/'):]), {}).get('alt', '')) for i in imgs))
                  for u, imgs in urls)
    fh.write('</urlset>\n')
print('sitemap: %d addresses, %d photos' % (len(urls), sum(len(i) for _, i in urls)))
