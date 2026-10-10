"""Find the recovered file behind a reference that doesn't resolve as written.

Shared by build_site.py (archive) and extract_content.py (modern site):
- image.php?file=X&w=N (thumbnails generated on the fly) -> the original file X
- popup.php?filename=X&general=G / ?general=G&img=N (gallery popups) -> the gallery photo
- N.jpg <-> 0N.jpg (also prefix_N.jpg <-> prefix_0N.jpg): the 2010 server copy zero-padded some photo names. A renamed file is
  used only in a folder where at least one other pair is proven byte-identical
  (and none differs), so a different photo with the same number is never swapped in.
"""
import posixpath, re
from urllib.parse import parse_qsl, urlparse


def _alt_names(name):
    m = re.match(r'^(\D*?)(\d+)(.*)$', name)      # N.jpg and prefix_N.jpg (conv_fash_1.jpg <-> conv_fash_01.jpg)
    if not m:
        return []
    pre, num, rest = m.groups()
    return [pre + num.lstrip('0') + rest] if num.startswith('0') and num.strip('0') else [pre + '0' + num + rest]


class Resolver:
    def __init__(self, keys, digest_of):
        """keys: iterable of canonical paths that exist; digest_of(path) -> content digest."""
        self.keys = set(keys)
        self.digest_of = digest_of
        self._verified = {}

    def _folder_ok(self, folder):
        if folder not in self._verified:
            same = differ = 0
            for k in self.keys:
                if posixpath.dirname(k) != folder:
                    continue
                for alt in _alt_names(posixpath.basename(k)):
                    other = posixpath.join(folder, alt)
                    if other in self.keys:
                        if self.digest_of(k) == self.digest_of(other):
                            same += 1
                        else:
                            differ += 1
            self._verified[folder] = same > 0 and differ == 0
        return self._verified[folder]

    def alternatives(self, key):
        """Canonical paths to try, best first, for a reference that didn't resolve."""
        p = urlparse(key)
        q = dict(parse_qsl(p.query))
        name = posixpath.basename(p.path)
        out = []
        if name == 'image.php' and q.get('file'):
            out.append('/' + q['file'].lstrip('/'))
        if name == 'popup.php' and q.get('general'):
            g = q['general']
            if q.get('filename'):
                out.append('/issues/general/%s/images/%s' % (g, q['filename']))
            if q.get('img'):
                out.append('/issues/general/%s/images/%s.jpg' % (g, q['img']))
        for cand in out[:] or [p.path]:
            folder = posixpath.dirname(cand)
            for alt in _alt_names(posixpath.basename(cand)):
                other = posixpath.join(folder, alt)
                if other in self.keys and self._folder_ok(folder):
                    out.append(other)
        return [c for c in out if c in self.keys]
