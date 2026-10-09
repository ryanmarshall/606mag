#!/usr/bin/env python3
"""Extract thumbnails and the filename catalog from Windows XP Thumbs.db files.

Thumbs.db is an OLE compound file: a "Catalog" stream lists the original image
filenames (with modification times), and each thumbnail is a stream named by its
catalog id written backwards ("12" -> "21") holding a small header plus a JPEG.

Usage: thumbsdb.py THUMBS_DB OUTDIR   -> OUTDIR/<original name>.jpg + catalog.json
"""
import datetime, json, os, re, struct, sys

src, outdir = sys.argv[1], sys.argv[2]
data = open(src, 'rb').read()
if data[:8] != bytes.fromhex('D0CF11E0A1B11AE1'):
    sys.exit('not an OLE compound file')

sec_size = 1 << struct.unpack_from('<H', data, 0x1E)[0]
mini_size = 1 << struct.unpack_from('<H', data, 0x20)[0]
n_fat, dir_start = struct.unpack_from('<II', data, 0x2C)
mini_cutoff, minifat_start, n_minifat, difat_start, n_difat = struct.unpack_from('<IIIII', data, 0x38)

def sector(i):
    off = (i + 1) * sec_size
    return data[off:off + sec_size]

difat = [x for x in struct.unpack_from('<109I', data, 0x4C)]
nxt = difat_start
for _ in range(n_difat):
    s = sector(nxt)
    ids = struct.unpack('<%dI' % (sec_size // 4), s)
    difat += ids[:-1]
    nxt = ids[-1]
fat = []
for i in difat[:n_fat]:
    fat += struct.unpack('<%dI' % (sec_size // 4), sector(i))

def chain(start, table):
    out, seen = [], set()
    while start < 0xFFFFFFFA and start not in seen and start < len(table):
        seen.add(start)
        out.append(start)
        start = table[start]
    return out

def read_stream(start, size):
    return b''.join(sector(i) for i in chain(start, fat))[:size]

# directory
dirdata = b''.join(sector(i) for i in chain(dir_start, fat))
entries = []
for off in range(0, len(dirdata), 128):
    e = dirdata[off:off + 128]
    nlen = struct.unpack_from('<H', e, 64)[0]
    name = e[:max(nlen - 2, 0)].decode('utf-16-le', 'replace')
    etype = e[66]
    start, size = struct.unpack_from('<II', e, 0x74)
    entries.append((name, etype, start, size))
root = next(e for e in entries if e[1] == 5)
ministream = read_stream(root[2], root[3])
minifat = []
for i in chain(minifat_start, fat):
    minifat += struct.unpack('<%dI' % (sec_size // 4), sector(i))

def get(name):
    for n, t, start, size in entries:
        if n == name and t == 2:
            if size < mini_cutoff:
                return b''.join(ministream[i * mini_size:(i + 1) * mini_size]
                                for i in chain(start, minifat))[:size]
            return read_stream(start, size)
    return None

# catalog: header (u16 len, u16 version, u32 count, u32 w, u32 h), then entries
cat = get('Catalog') or b''
catalog = []
if cat:
    hlen = struct.unpack_from('<H', cat, 0)[0]
    pos = hlen
    while pos + 16 <= len(cat):
        elen, eid, ft = struct.unpack_from('<IIQ', cat, pos)
        if elen < 16:
            break
        name = cat[pos + 16:pos + elen].decode('utf-16-le', 'replace').split('\x00')[0]
        when = (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
                ).strftime('%Y-%m-%d %H:%M') if ft else None
        catalog.append({'id': eid, 'name': name, 'modified': when})
        pos += elen

os.makedirs(outdir, exist_ok=True)
SAFE = re.compile(r'[^A-Za-z0-9._ -]+')
saved = 0
for item in catalog:
    blob = get(str(item['id'])[::-1])
    j = blob.find(b'\xff\xd8') if blob else -1
    if j < 0:
        item['thumbnail'] = None
        continue
    fn = SAFE.sub('_', item['name']) or str(item['id'])
    fn = os.path.splitext(fn)[0] + '.thumb.jpg'
    open(os.path.join(outdir, fn), 'wb').write(blob[j:])
    item['thumbnail'] = fn
    saved += 1
json.dump(catalog, open(os.path.join(outdir, 'catalog.json'), 'w'), indent=1)
print('%s: %d catalog entries, %d thumbnails extracted' % (os.path.basename(outdir), len(catalog), saved))
