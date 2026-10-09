#!/usr/bin/env python3
"""Make a built site work under any base path (ryanmarshall.github.io/606mag/ before the
domain moves, 606mag.com/ after, or straight from disk): every root-absolute reference on
the generated pages becomes relative to the page. The archive is already relative.

Covers href/src/background/action attributes, CSS url(), and the paths passed to the
2004 pages' MM_openBrWindow / MM_swapImage / MM_preloadImages helpers.

Usage: relativize_dist.py DIST_DIR
"""
import os, posixpath, re, sys

dist = sys.argv[1].rstrip('/')
ATTR = re.compile(r'''(\b(?:href|src|background|action)\s*=\s*)(["'])(/(?!/)[^"']*)\2''', re.I)
CSS = re.compile(r'''(url\(\s*)(["']?)(/(?!/)[^"')]*)\2(\s*\))''', re.I)
JS = re.compile(r'''(MM_(?:openBrWindow|swapImage|preloadImages)\([^)]*?)(['"])(/(?!/)[^'"]*)\2''')

def rel(target, page_dir):
    path, frag = (target.split('#', 1) + [''])[:2]
    path, query = (path.split('?', 1) + [''])[:2]
    r = posixpath.relpath(path.lstrip('/') or '.', page_dir or '.')
    if path.endswith('/') and r != '.':
        r += '/'
    if r == '.':
        r = './'
    return r + ('?' + query if query else '') + ('#' + frag if frag else '')

pages = changed = refs = 0
for dp, dirs, fs in os.walk(dist):
    rel_dir = os.path.relpath(dp, dist).replace(os.sep, '/')
    if rel_dir == 'archive' or rel_dir.startswith('archive/'):
        dirs[:] = []
        continue
    for f in fs:
        if not f.endswith('.html'):
            continue
        path = os.path.join(dp, f)
        page_dir = '' if rel_dir == '.' else rel_dir
        doc = open(path, encoding='utf-8').read()
        count = [0]
        def sub(m, group=3):
            count[0] += 1
            return m.group(1) + m.group(2) + rel(m.group(3), page_dir) + m.group(2) + (m.group(4) if m.lastindex >= 4 else '')
        new = ATTR.sub(sub, doc)
        new = CSS.sub(sub, new)
        # JS helpers may take several path arguments; repeat until none are root-absolute
        prev = None
        while prev != new:
            prev = new
            new = JS.sub(lambda m: (count.__setitem__(0, count[0] + 1) or
                                    m.group(1) + m.group(2) + rel(m.group(3), page_dir) + m.group(2)), new)
        pages += 1
        refs += count[0]
        if new != doc:
            changed += 1
            open(path, 'w', encoding='utf-8').write(new)
print('relativized %d references on %d of %d pages' % (refs, changed, pages))
