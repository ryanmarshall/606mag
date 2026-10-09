#!/usr/bin/env python3
"""Check whether the external links in the published pages still work.

A link is dead when its site doesn't resolve, errors, lands on a parked or
for-sale domain page, or now serves spam (many 2004 domains were re-registered
for casino/pharma/adult doorway pages). Results are cached in OUT_JSON so the
check can be re-run incrementally; the build de-links dead ones.

Usage: check_links.py OUT_JSON ROOT_DIR [ROOT_DIR ...]
"""
import concurrent.futures, html, json, os, re, socket, ssl, sys, time, urllib.error, urllib.request
from urllib.parse import urlparse

out_path, roots = sys.argv[1], sys.argv[2:]
HREF = re.compile(rb'''href\s*=\s*["']?\s*(https?://[^"'\s>]+)''', re.I)
OWN = {'606mag.com', 'www.606mag.com'}
PARKED = re.compile(rb'domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is parked|'
                    rb'parked (?:free|domain)|domain parking|related searches|sedoparking|hugedomains|'
                    rb'afternic|dan\.com|bodis\.com|parkingcrew|above\.com|this web page is parked|'
                    rb'is available for purchase|domain has expired|inquire about this domain', re.I)
PARK_HOSTS = re.compile(r'(sedo|hugedomains|afternic|dan\.com|bodis|parkingcrew|above\.com|godaddy|'
                        r'domainmarket|undeveloped|parklogic|namecheap)', re.I)
SPAM = re.compile(rb'\b(casino|slots?|poker|viagra|cialis|porn|xxx|payday|escort|betting|gambling|'
                  rb'sportsbook|baccarat|pharmacy|replica)\b', re.I)

urls = set()
for root in roots:
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(('.html', '.htm', '.php')):
                for m in HREF.finditer(open(os.path.join(dp, f), 'rb').read()):
                    u = html.unescape(m.group(1).decode('latin-1')).strip()
                    if urlparse(u).hostname and urlparse(u).hostname.lower() not in OWN:
                        urls.add(u)
results = json.load(open(out_path)) if os.path.exists(out_path) else {}
# re-check: earlier "blocked" answers under the current rules, and one slower retry for timeouts
for u, r in list(results.items()):
    if r.get('status') in (401, 403, 429) and not r.get('ok'):
        results[u].update(ok=True, why='HTTP %d (blocks automated checks; assumed working)' % r['status'])
retry = [u for u, r in results.items() if r.get('why') == 'TimeoutError' and not r.get('retried')]
todo = sorted(u for u in urls if u not in results)
print('external links: %d distinct, %d to check' % (len(urls), len(todo)), flush=True)

CTX = ssl.create_default_context()
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'

def check(url, timeout=12):
    rec = {'checked': time.strftime('%Y-%m-%d')}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,*/*'})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read(120000)
            rec.update(status=r.status, final=r.geturl())
    except urllib.error.HTTPError as e:
        # 401/403/429 usually mean "no bots", not "gone": the site answers people
        blocked = e.code in (401, 403, 429)
        rec.update(status=e.code, final=url, ok=blocked,
                   why=('HTTP %d (blocks automated checks; assumed working)' % e.code) if blocked else 'HTTP %d' % e.code)
        return url, rec
    except Exception as e:                                  # any failure to fetch = not working
        rec.update(status=None, ok=False, why=type(getattr(e, 'reason', e)).__name__)
        return url, rec
    final_host = urlparse(rec['final']).hostname or ''
    spam_terms = {m.group(1).lower().decode() for m in SPAM.finditer(body)}
    if PARK_HOSTS.search(final_host) or PARKED.search(body):
        rec.update(ok=False, why='parked or for-sale domain')
    elif len(spam_terms) >= 3:
        rec.update(ok=False, why='now a spam site (%s)' % ', '.join(sorted(spam_terms)[:4]))
    else:
        rec.update(ok=True)
    return url, rec

done = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
    for url, rec in pool.map(check, todo):
        results[url] = rec
        done += 1
        if done % 100 == 0:
            json.dump(results, open(out_path, 'w'), indent=0)
            print('  %d/%d checked' % (done, len(todo)), flush=True)
if retry:
    print('retrying %d timeouts with a 30s limit' % len(retry), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        for url, rec in pool.map(lambda u: check(u, 30), retry):
            rec['retried'] = True
            results[url] = rec
json.dump(results, open(out_path, 'w'), indent=0, sort_keys=True)
ok = sum(1 for u in urls if results.get(u, {}).get('ok'))
whys = {}
for u in urls:
    w = results.get(u, {}).get('why')
    if w:
        whys[w.split(' (')[0]] = whys.get(w.split(' (')[0], 0) + 1
print('working: %d   dead: %d   %s' % (ok, len(urls) - ok, dict(sorted(whys.items(), key=lambda kv: -kv[1]))))
