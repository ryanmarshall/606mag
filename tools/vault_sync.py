#!/usr/bin/env python3
"""Assemble the private vault (a separate private repository) from the project.

Copies what must be kept but never published: the database dump, the DreamHost
server copy of the magazine, the verified capture store and the working data.
Malware never leaves the machine: files flagged by malware_scan.py (minus the
verified false positives) and the attacker-only 2017 folder are left out and
listed in REMOVED.txt; passwords in include.php are redacted.

Usage: vault_sync.py PROJECT_DIR VAULT_DIR
"""
import hashlib, json, os, re, shutil, sys

project, vault = sys.argv[1:3]
SERVER = os.path.join(project, 'server-copy', 'extracted',
                      '606mag.com_DISABLED_FOR_MALWARE_SCRIPT_CONTACT_DREAMHOST_SUPPORT_cp')
SCAN = os.path.join(project, 'tools', 'scan_606mag.com_DISABLED_FOR_MALWAR.json')
FALSE_POSITIVES = {'PHP code inside non-PHP file'}
DEFACEMENT = re.compile(rb'<title>[^<]*hacked\s+by', re.I)

def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)

removed = []
# 1. server copy of the magazine, minus malware, passwords redacted
malware = set()
for r in json.load(open(SCAN)):
    real = [x for x in r['strong'] if x not in FALSE_POSITIVES and not
            (x == 'defacement marker' and r['path'].endswith('ChangeLog.txt'))]
    if real:
        malware.add(r['path'])
        removed.append(('server-copy', r['path'], r['size'], r['digest'], '; '.join(real)))
for rel in ('.logs/log1.txt',):
    malware.add(rel)
    removed.append(('server-copy', rel, os.path.getsize(os.path.join(SERVER, rel)), '', 'attacker spam-domain list'))
n = 0
for dp, _, fs in os.walk(SERVER):
    for f in fs:
        src = os.path.join(dp, f)
        rel = os.path.relpath(src, SERVER)
        if rel in malware:
            continue
        dst = os.path.join(vault, 'server-copy', '606mag.com', rel)
        if rel == 'include.php':
            data = open(src, 'rb').read()
            data = re.sub(rb'''(\$(?:sql|admin)_password\s*=\s*)(["']).*?\2''', rb'\1\2REDACTED\2', data)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(data)
        else:
            copy(src, dst)
        n += 1
print('server copy: %d files copied, %d malware files left out' % (n, len(malware)))

# 2. database dump (verbatim)
copy(os.path.join(project, 'server-copy', 'sixosix.sql.gz'), os.path.join(vault, 'database', 'sixosix.sql.gz'))
print('database dump copied')

# 3. verified capture store, minus defacement pages
blobs = os.path.join(project, 'archive-raw', '_blobs')
kept = 0
for b in os.listdir(blobs):
    with open(os.path.join(blobs, b), 'rb') as fh:
        if DEFACEMENT.search(fh.read(4096)):
            removed.append(('captures', b, os.path.getsize(os.path.join(blobs, b)), b, 'defacement page (Aug 2015)'))
            stale = os.path.join(vault, 'captures', '_blobs', b)
            if os.path.exists(stale):
                os.remove(stale)
            continue
    dst = os.path.join(vault, 'captures', '_blobs', b)
    if not os.path.exists(dst):
        copy(os.path.join(blobs, b), dst)
    kept += 1
copy(os.path.join(project, 'archive-raw', '_index.json'), os.path.join(vault, 'captures', '_index.json'))
print('captures: %d blobs' % kept)

# 4. working data
w = 0
for f in os.listdir(os.path.join(project, 'tools')):
    if f.endswith(('.json', '.jsonl')) and f != 'curation.json':
        copy(os.path.join(project, 'tools', f), os.path.join(vault, 'work', f)); w += 1
print('work files: %d' % w)

with open(os.path.join(vault, 'REMOVED.txt'), 'w') as out:
    out.write('Files deliberately NOT stored in this vault (malware / attacker content).\n'
              'Recorded here by path, size and SHA-1 (base32) for reference only.\n\n')
    out.write('Also not stored: the attacker-only folder 606mag.com_20170114044839 (1,362 files)\n'
              'and the derived SQLite database (regenerate with tools/dump_to_sqlite.py).\n\n')
    for where, path, size, digest, why in sorted(removed):
        out.write('%-11s %-70s %9s  %-32s  %s\n' % (where, path, size, digest, why))
print('REMOVED.txt: %d entries' % len(removed))
