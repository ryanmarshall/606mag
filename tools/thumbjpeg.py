#!/usr/bin/env python3
"""Decode Windows XP Thumbs.db thumbnails into PNGs (stdlib only).

XP stores thumbnails as "abbreviated" baseline JPEGs: no quantization (DQT) or
Huffman (DHT) tables, and four components labeled R, G, B, A. Standard decoders
reject them. This decoder supplies the JPEG standard (Annex K) Huffman tables and
the IJG quality-75 quantization table when they are absent, decodes every
component, and writes RGB PNGs.

Usage: thumbjpeg.py [--ycc] FILE.jpg ...   -> FILE.png beside each input
       --ycc  treat components 1-3 as YCbCr instead of RGB
"""
import math, struct, sys, zlib

ZZ = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34,
      27, 20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44,
      51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63]
BASE_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40,
             57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24,
             35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98,
             112, 100, 103, 99]
Q75 = [min(255, max(1, (BASE_LUMA[ZZ[k]] * 50 + 50) // 100)) for k in range(64)]  # zigzag order
DC_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
DC_VALS = list(range(12))
AC_BITS = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d]
AC_VALS = bytes.fromhex(
    '01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a'
    '25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a'
    '838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2'
    'd3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa')

def huff_table(bits, vals):
    table, code, k = {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            table[(length, code)] = vals[k]
            k += 1
            code += 1
        code <<= 1
    return table

COS = [[(math.sqrt(0.5) if u == 0 else 1.0) * math.cos((2 * x + 1) * u * math.pi / 16)
        for u in range(8)] for x in range(8)]

def idct(F):
    """F: 64 dequantized coefficients in natural order -> 64 samples."""
    tmp = [[sum(COS[y][v] * F[v * 8 + u] for v in range(8)) for u in range(8)] for y in range(8)]
    out = [0] * 64
    for y in range(8):
        row = tmp[y]
        for x in range(8):
            val = sum(COS[x][u] * row[u] for u in range(8)) / 4 + 128
            out[y * 8 + x] = 0 if val < 0 else 255 if val > 255 else int(round(val))
    return out

class Bits:
    def __init__(self, data, pos):
        self.d, self.p, self.acc, self.n = data, pos, 0, 0
    def bit(self):
        if self.n == 0:
            b = self.d[self.p] if self.p < len(self.d) else 0
            self.p += 1
            if b == 0xFF and self.p < len(self.d) and self.d[self.p] == 0:
                self.p += 1
            self.acc, self.n = b, 8
        self.n -= 1
        return (self.acc >> self.n) & 1
    def get(self, k):
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v
    def huff(self, table):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            if (length, code) in table:
                return table[(length, code)]
        raise ValueError('bad Huffman code')
    def restart(self):
        self.n = 0
        while self.p + 1 < len(self.d) and not (self.d[self.p] == 0xFF and 0xD0 <= self.d[self.p + 1] <= 0xD7):
            self.p += 1
        self.p += 2

def extend(v, t):
    return v - (1 << t) + 1 if t and v < (1 << (t - 1)) else v

def decode(data):
    qt, dc_t, ac_t = {}, {}, {}
    comps, w, h, interval, pos = [], 0, 0, 0, 2
    while pos < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        m = data[pos + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        L = struct.unpack_from('>H', data, pos + 2)[0]
        seg = data[pos + 4:pos + 2 + L]
        if m == 0xDB:
            i = 0
            while i < len(seg):
                tq = seg[i] & 15
                qt[tq] = list(seg[i + 1:i + 65])
                i += 65
        elif m == 0xC4:
            i = 0
            while i < len(seg):
                tc, th = seg[i] >> 4, seg[i] & 15
                bits = list(seg[i + 1:i + 17])
                n = sum(bits)
                (ac_t if tc else dc_t)[th] = huff_table(bits, seg[i + 17:i + 17 + n])
                i += 17 + n
        elif m == 0xDD:
            interval = struct.unpack_from('>H', seg, 0)[0]
        elif m == 0xC0:
            h, w = struct.unpack_from('>HH', seg, 1)
            for i in range(seg[5]):
                cid, samp, tq = seg[6 + 3 * i:9 + 3 * i]
                comps.append({'id': cid, 'tq': tq})
        elif m == 0xDA:
            for i in range(seg[0]):
                cid, tables = seg[1 + 2 * i:3 + 2 * i]
                c = next(c for c in comps if c['id'] == cid)
                c['td'], c['ta'] = tables >> 4, tables & 15
            pos = pos + 2 + L
            break
        pos += 2 + L
    for c in comps:
        c['q'] = qt.get(c['tq'], Q75)
        c['dct'] = dc_t.get(c['td']) or huff_table(DC_BITS, DC_VALS)
        c['act'] = ac_t.get(c['ta']) or huff_table(AC_BITS, AC_VALS)
        c['pred'] = 0
        c['plane'] = [[0] * (((w + 7) // 8) * 8) for _ in range(((h + 7) // 8) * 8)]
    br = Bits(data, pos)
    mcus_x, mcus_y = (w + 7) // 8, (h + 7) // 8
    for n in range(mcus_x * mcus_y):
        if interval and n and n % interval == 0:
            br.restart()
            for c in comps:
                c['pred'] = 0
        my, mx = divmod(n, mcus_x)
        for c in comps:
            t = br.huff(c['dct'])
            c['pred'] += extend(br.get(t), t)
            F = [0] * 64
            F[0] = c['pred'] * c['q'][0]
            k = 1
            while k < 64:
                rs = br.huff(c['act'])
                r, s = rs >> 4, rs & 15
                if s == 0:
                    if r != 15:
                        break
                    k += 16
                    continue
                k += r
                if k > 63:
                    break
                F[ZZ[k]] = extend(br.get(s), s) * c['q'][k]
                k += 1
            px = idct(F)
            for y in range(8):
                c['plane'][my * 8 + y][mx * 8:mx * 8 + 8] = px[y * 8:y * 8 + 8]
    return w, h, [c['plane'] for c in comps]

def write_png(path, w, h, rows):
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

def clamp(v):
    return 0 if v < 0 else 255 if v > 255 else int(round(v))

ycc = '--ycc' in sys.argv
for path in [a for a in sys.argv[1:] if a != '--ycc']:
    try:
        w, h, planes = decode(open(path, 'rb').read())
    except Exception as e:
        print('FAILED %s: %s' % (path, e))
        continue
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            a, b, c = planes[0][y][x], planes[1][y][x], planes[2][y][x] if len(planes) > 2 else 0
            if ycc:
                row += [clamp(a + 1.402 * (c - 128)), clamp(a - 0.344136 * (b - 128) - 0.714136 * (c - 128)),
                        clamp(a + 1.772 * (b - 128))]
            else:
                row += [a, b, c] if len(planes) > 2 else [a, a, a]
        rows.append(row)
    out = path[:-4] + ('.ycc' if ycc else '') + '.png'
    write_png(out, w, h, rows)
    print('%s -> %s (%dx%d, %d components)' % (path.split('/')[-1], out.split('/')[-1], w, h, len(planes)))
