#!/usr/bin/env python3
"""Audit everything a public git repository exposes: every commit on every ref, every
file version in history, and commit metadata. Run before every push to the public repo.

Checks, without ever printing a secret: the old passwords from the server copy's
include.php, the database's subscriber emails, any email address, IPv4 addresses,
references to private folders, malware signatures, and author/committer emails.

Usage: publish_audit.py REPO_DIR INCLUDE_PHP DUMP_SQL_GZ
"""
import gzip, re, subprocess, sys

repo, include_php, dump = sys.argv[1:4]
git = lambda *a: subprocess.run(['git', '-C', repo] + list(a), capture_output=True).stdout

secrets = [m.group(1) for m in re.finditer(rb'''\$(?:sql|admin)_password\s*=\s*["']([^"']+)["']''',
                                           open(include_php, 'rb').read())]
subscribers = set()
with gzip.open(dump, 'rb') as f:
    for line in f:
        if line.startswith(b'INSERT INTO `emails` VALUES'):
            for h in re.findall(rb"0x([0-9A-Fa-f]+)|'([^']*)'", line):
                v = bytes.fromhex(h[0].decode()) if h[0] else h[1]
                if b'@' in v:
                    subscribers.add(v.strip().lower())
EMAIL = re.compile(rb'[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}', re.I)
IPV4 = re.compile(rb'(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])')
PRIVATE = re.compile(rb'server-copy/extracted|sixosix\.sql|606mag-vault/|\bcandid\b|archive-raw/_blobs/[A-Z2-7]{32}')
MALWARE = re.compile(rb'(eval|assert)\s*\(\s*(base64_decode|gzinflate|str_rot13)|FilesMan|hacked\s+by|'
                     rb'(\$\w+\s*\[\s*\d+\s*\]\s*\.\s*){8,}', re.I)
ALLOWED_EMAILS = {b'noreply@anthropic.com'}
# the pipeline's own scripts legitimately contain detection signatures and local paths
RULE_FILES = re.compile(r'^tools/[^/]+\.(py|sh)$')

commits = git('rev-list', '--all').split()
print('refs: %s' % ' '.join(git('for-each-ref', '--format=%(refname:short)').decode().split()))
print('commits in history: %d' % len(commits))
people = set()
for line in git('log', '--all', '--format=%an <%ae>%n%cn <%ce>').decode().splitlines():
    people.add(line)
print('identities in commit metadata: %s' % sorted(people))

objects = [l.split(b' ', 1) for l in git('rev-list', '--all', '--objects').splitlines()]
blobs = {}
for parts in objects:
    sha = parts[0].decode()
    if git('cat-file', '-t', sha).strip() == b'blob':
        blobs[sha] = parts[1].decode() if len(parts) > 1 else '?'
print('file versions (blobs) in history: %d' % len(blobs))
findings = {k: [] for k in ('password', 'subscriber email', 'other email', 'IPv4', 'private reference', 'malware')}
for sha, path in sorted(blobs.items(), key=lambda kv: kv[1]):
    data = git('cat-file', '-p', sha)
    textual = b'\x00' not in data[:4096]
    if any(s in data for s in secrets):
        findings['password'].append(path)
    if not textual:
        continue
    emails = {e.lower() for e in EMAIL.findall(data)} - ALLOWED_EMAILS
    if emails & subscribers:
        findings['subscriber email'].append(path)
    elif emails:
        findings['other email'].append('%s (%d)' % (path, len(emails)))
    if IPV4.search(data):
        findings['IPv4'].append(path)
    if RULE_FILES.match(path):
        continue
    if PRIVATE.search(data):
        findings['private reference'].append(path)
    if MALWARE.search(data):
        findings['malware'].append(path)
print('subscriber emails checked against: %d' % len(subscribers))
for k, v in findings.items():
    print('  %-18s %s' % (k, ', '.join(v[:8]) + (' ...(+%d)' % (len(v) - 8) if len(v) > 8 else '') if v else 'none'))
