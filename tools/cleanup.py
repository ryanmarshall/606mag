"""Page cleanup for the rebuilt site (used by build_site.py).

Removes dead third-party code (2006 AdSense, 2008 ga.js, and every other external
script: ad-network domains from 2005 are often re-registered by malware
distributors), the markup of the site's own 2004-2006 phpAdsNew ad server, and
reader-comment spam (see comments.py).
"""
import re

from comments import strip_spam

SCRIPT_EL = re.compile(r'<script\b[^>]*>.*?</script\s*>', re.I | re.S)
TRACKER_SIG = re.compile(r'googlesyndication\.com|google_ad_client|google-analytics\.com|'
                         r'_gat\._getTracker|urchinTracker|gaJsHost|pageTracker\.', re.I)
EXTERNAL_SRC = re.compile(r'<script\b[^>]*\bsrc\s*=\s*["\']?\s*(?:https?:)?//'
                          r'(?!(?:www\.)?606mag\.com)', re.I)
AD_MARKUP = [re.compile(x, re.I | re.S) for x in (
    r'<a\b[^>]*phpad/adclick[^>]*>.*?</a>',
    r'<div\b[^>]*id\s*=\s*["\']?beacon_\d+[^>]*>.*?</div>',
    r'<noscript>(?:(?!</noscript>).)*phpad/(?:(?!</noscript>).)*</noscript>',
    r'<iframe\b[^>]*phpad[^>]*>.*?</iframe>',
    r'<img\b[^>]*phpad/[^>]*>')]
# 2004-era email obfuscation (Hiveware Enkoder): benign, ignored by the security scan
ENKODER = re.compile(r'<script\b[^>]*>(?:(?!</script>).)*hiveware_enkoder(?:(?!</script>).)*'
                     r'</script\s*>', re.I | re.S)


def clean(doc, stats):
    def script(m):
        el = m.group(0)
        if TRACKER_SIG.search(el) or EXTERNAL_SRC.match(el) or 'phpad/' in el:
            stats['third-party/ad scripts stripped'] += 1
            return ''
        return el
    doc = SCRIPT_EL.sub(script, doc)
    for rx in AD_MARKUP:
        doc, n = rx.subn('', doc)
        stats['ad-server elements stripped'] += n
    doc, removed, kept = strip_spam(doc)
    stats['spam comments removed'] += removed
    stats['reader comments kept'] += kept
    return doc
