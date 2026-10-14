#!/usr/bin/env python3
"""Write DIST/sitemap.xml for search engines: every page of the build (rebuilt and archive)
except the old-link page, the "not archived" notice, include fragments, and archive copies
that name a rebuilt page as canonical (tools/inject_archive_tags.py). No <lastmod>: the
pages are from 2004 and a build date would be false.

Usage: make_sitemap.py DIST_DIR SITE_URL
"""
import os, re, sys
from urllib.parse import quote
from xml.sax.saxutils import escape

dist, site_url = sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/')
SKIP = {'404.html', 'archive/_missing.html'}
PAGE = re.compile(r'<head\b|^<!doctype html', re.I)
urls = []
for dp, dirs, files in os.walk(dist):
    dirs.sort()
    for name in sorted(files):
        if not name.endswith('.html'):
            continue
        rel = os.path.relpath(os.path.join(dp, name), dist).replace(os.sep, '/')
        if rel in SKIP:
            continue
        head = open(os.path.join(dp, name), encoding='utf-8', errors='replace').read(6000)
        if not PAGE.search(head) or 'rel="canonical"' in head:
            continue
        path = rel[:-len('index.html')] if name == 'index.html' else rel
        urls.append(site_url + '/' + quote(path))
if len(urls) > 50000:
    sys.exit('make_sitemap: %d addresses is over the 50,000 a sitemap may hold' % len(urls))
with open(os.path.join(dist, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    fh.writelines('<url><loc>%s</loc></url>\n' % escape(u) for u in urls)
    fh.write('</urlset>\n')
print('sitemap: %d addresses' % len(urls))
