#!/usr/bin/env python3
"""First look at a mysqldump file without executing any of it: per table, the
CREATE TABLE definition, number of INSERT statements, and bytes of data.

Usage: dump_inspect.py DUMP.sql.gz OUT_JSON
"""
import gzip, json, re, sys
from collections import defaultdict

dump, out_path = sys.argv[1:3]
CREATE = re.compile(rb'^CREATE TABLE `([^`]+)`')
INSERT = re.compile(rb'^INSERT INTO `([^`]+)` VALUES ')
tables = defaultdict(lambda: {'create': '', 'inserts': 0, 'bytes': 0, 'approx_rows': 0})
current = None
with gzip.open(dump, 'rb') as f:
    for line in f:
        m = CREATE.match(line)
        if m:
            current = m.group(1).decode()
            tables[current]['create'] = line.decode('latin-1')
            continue
        if current and tables[current]['create'] and not tables[current]['create'].rstrip().endswith(';'):
            tables[current]['create'] += line.decode('latin-1')
        m = INSERT.match(line)
        if m:
            t = tables[m.group(1).decode()]
            t['inserts'] += 1
            t['bytes'] += len(line)
            t['approx_rows'] += line.count(b'),(') + 1
for t in tables.values():
    t['columns'] = re.findall(r'^\s+`([^`]+)` ([^\s,]+(?: unsigned)?)', t['create'], re.M)
    cs = re.search(r'CHARSET=(\w+)', t['create'])
    t['charset'] = cs.group(1) if cs else '?'
    eng = re.search(r'ENGINE=(\w+)', t['create'])
    t['engine'] = eng.group(1) if eng else '?'
json.dump(tables, open(out_path, 'w'), indent=1)
AD = re.compile(r'^(phpads_|ad_)')
print('%-28s %10s %9s  %-8s %s' % ('table', '~rows', 'MB', 'charset', 'columns'))
for name, t in sorted(tables.items(), key=lambda kv: -kv[1]['bytes']):
    if AD.match(name):
        continue
    cols = ', '.join(c for c, _ in t['columns'])
    print('%-28s %10d %9.1f  %-8s %s' % (name, t['approx_rows'], t['bytes'] / 1e6, t['charset'], cols[:95]))
skipped = [n for n in tables if AD.match(n)]
print('\nad tables skipped (%d): %.1f MB' % (len(skipped), sum(tables[n]['bytes'] for n in skipped) / 1e6))
