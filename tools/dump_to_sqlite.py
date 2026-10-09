#!/usr/bin/env python3
"""Load the content tables of the sixosix mysqldump into a local SQLite file.

The dump is parsed as data with a tokenizer; none of its SQL is executed. Text is
decoded per value (UTF-8 if valid, else cp1252, which is what MySQL calls latin1).
Values are stored exactly as in the database, including the backslash-escaped
quotes the 2004 PHP code saved (it stripped them on output).
Privacy: subscriber emails, logins/passwords and visitor IPs are never stored -
those tables are only counted, and page views are kept as per-article totals.
The phpAdsNew ad tables are skipped entirely.

Usage: dump_to_sqlite.py DUMP.sql.gz OUT.sqlite
"""
import gzip, re, sqlite3, sys
from collections import defaultdict

dump, out = sys.argv[1:3]
SKIP = re.compile(r'^(phpads_|ad_)')
COUNT_ONLY = {'emails', 'users', 'schedule_users', 'page_views', 'cs_comments', 'schedule_config'}
DROP_COLUMNS = {'stories_user': {'login', 'password'}}
CREATE = re.compile(rb'^CREATE TABLE `([^`]+)`')
COLUMN = re.compile(rb'^\s+`([^`]+)` (\w+)')
INSERT = re.compile(rb'^INSERT INTO `([^`]+)` VALUES ')
TOKEN = re.compile(rb"""\s*(?:
      _binary\s*'([^'\\]*(?:\\.[^'\\]*)*)'
    | '([^'\\]*(?:\\.[^'\\]*)*)'
    | (0x[0-9A-Fa-f]*)
    | (NULL)
    | (-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
    | ([(),;])
    )""", re.X | re.S)
ESC = {b'0': b'\x00', b'b': b'\x08', b'n': b'\n', b'r': b'\r', b't': b'\t', b'Z': b'\x1a'}
UNESCAPE = re.compile(rb'\\(.)', re.S)

def unescape(b):
    return UNESCAPE.sub(lambda m: ESC.get(m.group(1), m.group(1)), b)

def decode(b):
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return ''.join(chr(c) if c in (0x81, 0x8d, 0x8f, 0x90, 0x9d) else bytes([c]).decode('cp1252')
                       for c in b) if any(0x80 <= c < 0xa0 for c in b) else b.decode('latin-1')

def rows(line, start):
    """Yield one list of Python values per (...) tuple in an INSERT line."""
    pos, row = start, None
    while pos < len(line):
        m = TOKEN.match(line, pos)
        if not m:
            raise ValueError('unparseable at byte %d: %r' % (pos, line[pos:pos + 40]))
        pos = m.end()
        binstr, s, hexv, null, num, punct = m.groups()
        if punct == b'(':
            row = []
        elif punct == b')':
            yield row
            row = None
        elif punct in (b',', b';') or punct is None and m.group(0).strip() == b'':
            if punct == b';':
                return
        elif s is not None or binstr is not None:
            row.append(('str', unescape(s if s is not None else binstr)))
        elif hexv is not None:
            row.append(('bin', bytes.fromhex(hexv[2:].decode())))
        elif null is not None:
            row.append(None)
        else:
            row.append(float(num) if b'.' in num or b'e' in num.lower() else int(num))

db = sqlite3.connect(out)
schema, kinds, counts = {}, {}, defaultdict(int)
views = defaultdict(lambda: [0, None, None])     # article_id -> [count, first, last]
current = None
with gzip.open(dump, 'rb') as f:
    for line in f:
        m = CREATE.match(line)
        if m:
            current = m.group(1).decode()
            schema[current], kinds[current] = [], []
            continue
        if current and line.startswith(b')'):
            name = current
            current = None
            if SKIP.match(name) or name in COUNT_ONLY or name == 'view_stats':
                continue
            keep = [c for c in schema[name] if c not in DROP_COLUMNS.get(name, ())]
            db.execute('DROP TABLE IF EXISTS "%s"' % name)
            db.execute('CREATE TABLE "%s" (%s)' % (name, ', '.join('"%s"' % c for c in keep)))
            continue
        if current:
            c = COLUMN.match(line)
            if c:
                schema[current].append(c.group(1).decode())
                kinds[current].append(c.group(2).decode().lower())
            continue
        m = INSERT.match(line)
        if not m:
            continue
        name = m.group(1).decode()
        if SKIP.match(name):
            continue
        cols = schema[name]
        for row in rows(line, m.end()):
            counts[name] += 1
            if name in COUNT_ONLY:
                continue
            if name == 'view_stats':        # aggregate only: no IPs or sessions kept
                rec = dict(zip(cols, row))
                aid, ts = rec.get('article_id'), rec.get('date_stamp')
                aid = decode(aid[1]) if isinstance(aid, tuple) else aid
                ts = int(decode(ts[1])) if isinstance(ts, tuple) else ts
                v = views[str(aid)]
                v[0] += 1
                v[1] = ts if v[1] is None or (ts and ts < v[1]) else v[1]
                v[2] = ts if v[2] is None or (ts and ts > v[2]) else v[2]
                continue
            vals = []
            for col, kind, val in zip(cols, kinds[name], row):
                if col in DROP_COLUMNS.get(name, ()):
                    continue
                if isinstance(val, tuple):
                    # with --default-character-set=binary mysqldump hex-encodes text columns
                    # too, so the column type decides what is text
                    binary = 'blob' in kind or kind in ('binary', 'varbinary')
                    val = val[1] if binary else decode(val[1])
                vals.append(val)
            db.execute('INSERT INTO "%s" VALUES (%s)' % (name, ','.join('?' * len(vals))), vals)
db.execute('DROP TABLE IF EXISTS article_views')
db.execute('CREATE TABLE article_views (article_id, views, first_view, last_view)')
db.executemany('INSERT INTO article_views VALUES (?,?,?,?)',
               [(k, v[0], v[1], v[2]) for k, v in views.items()])
db.execute('DROP TABLE IF EXISTS _row_counts')
db.execute('CREATE TABLE _row_counts (tbl, rows, stored)')
db.executemany('INSERT INTO _row_counts VALUES (?,?,?)',
               [(t, n, 0 if (t in COUNT_ONLY or t == 'view_stats') else 1) for t, n in sorted(counts.items())])
db.commit()
for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
    note = 'counted only (private)' if t in COUNT_ONLY else 'aggregated per article (no IPs)' if t == 'view_stats' else 'stored'
    print('  %-24s %9d rows   %s' % (t, n, note))
