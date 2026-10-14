#!/usr/bin/env python3
"""Find pages Google's ad policies would restrict, for choosing web/src/data/ads.json "noAds".

Scans the rebuilt issue pages (text, the comments each page shows, image names) with
word-boundary patterns for sexual subjects, strong profanity and slurs, and ranks articles.
It decides nothing: the owner confirms the list. Writes tools/ad_review.json (git-ignored);
--sheet FILE.html also writes a local contact sheet of each candidate's images, which have to
be looked at (photos and lettering in images can't be judged from words).

Usage: ad_review.py [--sheet FILE.html]
"""
import html, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
W = lambda *words: re.compile(r'\b(?:%s)\b' % '|'.join(words), re.I)
CATEGORIES = {
    'sexual': W(r'nude', r'nudity', r'naked', r'topless', r'porn\w*', r'strippers?', r'strip clubs?', r'burlesque',
                r'fetish\w*', r'bondage', r'escorts?', r'hookers?', r'prostitut\w+', r'sex', r'sexual\w*', r'erotic\w*',
                r'penis', r'vaginal?', r'breasts?', r'boobs?', r'tits', r'thongs?', r'masturbat\w+', r'orgasm\w*',
                r'suicide ?girls?', r'playboy', r'lap ?dances?'),
    'strong': W(r'fuck\w*', r'motherf\w*', r'cunts?', r'cocks?', r'cocksuck\w*', r'pussy', r'twats?', r'sluts?', r'whores?'),
    'mild': W(r'shit\w*', r'bitch\w*', r'assholes?', r'dicks?', r'bastards?', r'damn\w*'),
    'slur': W(r'fag\w*', r'retard\w*', r'nigg\w*', r'midgets?', r'trann\w*', r'spics?'),
}
SUGGESTIVE_IMG = re.compile(r'(nude|naked|sex|strip|burlesque|bra|boob|tit|ass|sg_|suicide|playboy|vag)', re.I)
IMG = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.I)

articles = json.load(open(os.path.join(ROOT, 'web/src/data/articles.json')))
issues = {i['number'] for i in json.load(open(os.path.join(ROOT, 'web/src/data/issues.json')))}
ads = json.load(open(os.path.join(ROOT, 'web/src/data/ads.json')))
listed = {e['url'] for e in ads['noAds']}

def text_of(fragment):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment)))

report = []
for a in articles:
    if a['issue'] not in issues:
        continue                                   # general-section articles aren't built
    comments = ' '.join('%s %s %s' % (c['subject'], c['name'], c['text']) for c in a['comments'])
    hits, snippets, images = {k: 0 for k in CATEGORIES}, [], set()
    words = 0
    for p in a['pages']:
        t = text_of(p['html'] + p.get('tail', '')) + (' ' + text_of(comments) if p['comments'] else '')
        words += len(t.split())
        for k, rx in CATEGORIES.items():
            for m in rx.finditer(t):
                hits[k] += 1
                if len(snippets) < 8 and k != 'mild':
                    snippets.append('%s: …%s…' % (k, t[max(0, m.start() - 60):m.end() + 60].strip()))
        images.update(IMG.findall(p['html']))
    per_k = lambda k: hits[k] * 1000 / max(words, 1)
    tier = ('exclude' if hits['slur'] or re.search(r'\bcunts?\b', comments + ' '.join(p['html'] for p in a['pages']), re.I)
            or per_k('strong') >= 3 or per_k('sexual') >= 4 else
            'review' if hits['sexual'] or hits['strong'] else 'ok')
    report.append({'url': a['url'], 'title': a['title'], 'tier': tier, 'listed': a['url'] in listed, 'words': words,
                   'hits': hits, 'snippets': snippets, 'images': sorted(images),
                   'suggestiveImages': sorted(i for i in images if SUGGESTIVE_IMG.search(os.path.basename(i)))})
order = {'exclude': 0, 'review': 1, 'ok': 2}
report.sort(key=lambda r: (order[r['tier']], -(r['hits']['sexual'] + r['hits']['strong'] + 3 * r['hits']['slur'])))
json.dump(report, open(os.path.join(ROOT, 'tools/ad_review.json'), 'w'), indent=1)
for r in report:
    if r['tier'] != 'ok':
        print('%-8s %s %-48s sexual %-3d strong %-3d slur %-2d mild %-3d words %d' % (
            r['tier'], '*' if r['listed'] else ' ', r['url'], r['hits']['sexual'], r['hits']['strong'], r['hits']['slur'],
            r['hits']['mild'], r['words']))
print('(* = already in ads.json noAds)')

if '--sheet' in sys.argv:
    out = sys.argv[sys.argv.index('--sheet') + 1]
    site = os.path.realpath(os.path.join(ROOT, 'site'))
    parts = ['<!doctype html><meta charset="utf-8"><title>606mag ad review</title><style>body{font:13px Arial;margin:20px}'
             'img{height:110px;margin:2px;vertical-align:top}h2{font-size:15px;margin:24px 0 4px}p{margin:2px 0;color:#555}</style>']
    for r in report:
        if r['tier'] == 'ok' and len(r['images']) < 5:
            continue
        parts.append('<h2>%s · %s · %s</h2>' % (r['tier'], html.escape(r['url']), html.escape(r['title'])))
        parts += ['<p>%s</p>' % html.escape(s) for s in r['snippets'][:4]]
        parts += ['<img src="file://%s" title="%s">' % (html.escape(site + i[len('/archive'):]), html.escape(i))
                  for i in r['images'] if i.startswith('/archive/')]
    open(out, 'w', encoding='utf-8').write(''.join(parts))
    print('contact sheet:', out)
