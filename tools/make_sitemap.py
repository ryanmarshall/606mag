#!/usr/bin/env python3
"""Write DIST/sitemap.xml for search engines: every page of the build (rebuilt and archive)
except the old-link page, the "not archived" notice, include fragments, and archive copies
that name a rebuilt page as canonical (tools/inject_archive_tags.py). Each page also lists
its photos (images tools/image_alt.json describes as photos or pictures with words), so
they can appear in image search. No <lastmod>: the pages are from 2004 and a build date
would be false. Run before relativize_dist.py (rebuilt pages still use /archive/... paths).

Usage: make_sitemap.py DIST_DIR SITE_URL
"""
import json, os, posixpath, re, sys
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

dist, site_url = sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/')
SKIP = {'404.html', 'archive/_missing.html'}
PAGE = re.compile(r'<head\b|^<!doctype html', re.I)
IMG_SRC = re.compile(r'''<img\b[^>]*?\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''', re.I)
alt_map = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image_alt.json'), encoding='utf-8'))['images']

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
        if not PAGE.search(doc[:6000]) or 'rel="canonical"' in doc[:6000]:
            continue
        path = rel[:-len('index.html')] if name == 'index.html' else rel
        urls.append((site_url + '/' + quote(path), [site_url + '/archive/' + quote(p) for p in photos(doc, posixpath.dirname(rel))]))
if len(urls) > 50000:
    sys.exit('make_sitemap: %d addresses is over the 50,000 a sitemap may hold' % len(urls))
with open(os.path.join(dist, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
             ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n')
    fh.writelines('<url><loc>%s</loc>%s</url>\n' % (escape(u), ''.join(
        '<image:image><image:loc>%s</image:loc></image:image>' % escape(i) for i in imgs)) for u, imgs in urls)
    fh.write('</urlset>\n')
print('sitemap: %d addresses, %d photos' % (len(urls), sum(len(i) for _, i in urls)))
