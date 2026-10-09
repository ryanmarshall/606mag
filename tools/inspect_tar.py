#!/usr/bin/env python3
"""List a tar archive without extracting it, flagging anything unsafe to unpack:
absolute paths, '..' components, links, device/fifo entries, setuid/setgid bits.

Usage: inspect_tar.py ARCHIVE
"""
import stat, sys, tarfile, time
from collections import Counter

tf = tarfile.open(sys.argv[1], 'r:gz')
members = tf.getmembers()
flags, kinds, tops, years, execs = [], Counter(), Counter(), Counter(), 0
for m in members:
    kind = ('dir' if m.isdir() else 'file' if m.isfile() else 'symlink' if m.issym() else
            'hardlink' if m.islnk() else 'device/fifo' if (m.ischr() or m.isblk() or m.isfifo()) else 'other')
    kinds[kind] += 1
    tops[m.name.split('/')[0]] += 1
    if m.isfile():
        years[time.gmtime(m.mtime).tm_year] += 1
        execs += bool(m.mode & 0o111)
    if m.name.startswith('/') or '..' in m.name.split('/'):
        flags.append(('path escapes target', m.name))
    if m.issym() or m.islnk():
        flags.append(('%s -> %s' % (kind, m.linkname), m.name))
    if kind in ('device/fifo', 'other'):
        flags.append((kind, m.name))
    if m.mode & (stat.S_ISUID | stat.S_ISGID):
        flags.append(('setuid/setgid bit', m.name))
print('entries: %d   %s' % (len(members), dict(kinds)))
print('top-level folders:', dict(tops))
print('files with execute bit set: %d' % execs)
print('file modification years:', dict(sorted(years.items())))
print('unsafe entries: %d' % len(flags))
for why, name in flags[:40]:
    print('   %-28s %s' % (why, name))
