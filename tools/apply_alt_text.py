#!/usr/bin/env python3
"""Give the images of a build their alt text: what lettering images say, what photos show,
and an empty alt for decoration (tools/image_alt.json, written by describing every image the
site shows). Applies to the rebuilt pages and the archive pages alike, wherever the
same image file appears; images without an entry are left as they are. The articles' photos
use their alt text in context (tools/image_alt_context.json, from tools/make_seo.py): the
article, its credits and, for the lead photo, its summary, then what the picture shows.

Run on the build output before relativize_dist.py (rebuilt pages still use /archive/... paths;
archive pages use paths relative to themselves). Line endings are kept.

Usage: apply_alt_text.py DIST_DIR
"""
import html, json, os, posixpath, re, sys
from urllib.parse import unquote

dist = sys.argv[1].rstrip('/')
here = os.path.dirname(os.path.abspath(__file__))
images = json.load(open(os.path.join(here, 'image_alt.json'), encoding='utf-8'))['images']
# the articles' photos in context: which article, by whom, what it's about (tools/make_seo.py)
for key, alt in json.load(open(os.path.join(here, 'image_alt_context.json'), encoding='utf-8'))['images'].items():
    if key in images:
        images[key] = dict(images[key], alt=alt)

IMG = re.compile(r'<img\b[^>]*>', re.I)
SRC = re.compile(r'''\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''', re.I)
ALT = re.compile(r'''\s+alt\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)''', re.I)

def site_path(src, page_dir):
    """The image's path inside the archive (site/), or None for other images."""
    src = unquote(src.split('?')[0].split('#')[0])
    if src.startswith('/archive/'):
        return src[len('/archive/'):]
    if src.startswith(('/', 'http:', 'https:', 'data:')) or not page_dir.startswith('archive'):
        return None
    p = posixpath.normpath(posixpath.join(page_dir, src))
    return p[len('archive/'):] if p.startswith('archive/') else None

pages = changed = tags = 0
for dp, dirs, files in os.walk(dist):
    dirs.sort()
    for name in sorted(files):
        if not name.endswith('.html'):
            continue
        path = os.path.join(dp, name)
        page_dir = posixpath.dirname(os.path.relpath(path, dist).replace(os.sep, '/'))
        with open(path, encoding='utf-8', newline='') as fh:
            doc = fh.read()
        def fix(m):
            global tags
            tag = m.group(0)
            s = SRC.search(tag)
            entry = images.get(site_path(next(g for g in s.groups() if g is not None), page_dir)) if s else None
            if entry is None:
                return tag
            tags += 1
            bare = ALT.sub('', tag)
            end = len(bare) - (2 if bare.endswith('/>') else 1)
            return bare[:end].rstrip() + ' alt="%s"' % html.escape(entry['alt'], quote=True) + bare[end:]
        new = IMG.sub(fix, doc)
        pages += 1
        if new != doc:
            with open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(new)
            changed += 1
print('alt text: %d image tags on %d of %d pages' % (tags, changed, pages))
