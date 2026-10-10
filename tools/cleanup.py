"""Page cleanup for the rebuilt site (used by build_site.py).

Removes dead third-party code (2006 AdSense, 2008 ga.js, and every other external
script: ad-network domains from 2005 are often re-registered by malware
distributors), the markup of the site's own 2004-2006 phpAdsNew ad server, and
reader-comment spam (see comments.py).
"""
import re

from comments import anonymize_qa, strip_qa_spam, strip_spam

SCRIPT_EL = re.compile(r'<script\b[^>]*>.*?</script\s*>', re.I | re.S)
TRACKER_SIG = re.compile(r'googlesyndication\.com|google_ad_client|google-analytics\.com|'
                         r'_gat\._getTracker|urchinTracker|gaJsHost|pageTracker\.|advertising\.com|'
                         r"<SCR'\s*\+\s*'IPT|document\.write\s*\(\s*['\"]<\s*scr", re.I)
EXTERNAL_SRC = re.compile(r'<script\b[^>]*\bsrc\s*=\s*["\']?\s*(?:https?:)?//'
                          r'(?!(?:www\.)?606mag\.com)', re.I)
AD_MARKUP = [re.compile(x, re.I | re.S) for x in (
    r'<a\b[^>]*phpad/adclick[^>]*>.*?</a>',
    r'<div\b[^>]*id\s*=\s*["\']?beacon_\d+[^>]*>.*?</div>',
    r'<noscript>(?:(?!</noscript>).)*phpad/(?:(?!</noscript>).)*</noscript>',
    r'<iframe\b[^>]*phpad[^>]*>.*?</iframe>',
    r'<img\b[^>]*phpad/[^>]*>')]
# SEO spam injected into the 2009 front page: invisible links to unrelated sites
HIDDEN_LINK = re.compile(r'<a\b[^>]*style\s*=\s*["\'][^"\']*display\s*:\s*none[^"\']*["\'][^>]*>.*?</a\s*>',
                         re.I | re.S)
# HTML comments are invisible but still published; the ones holding links carried injected
# image-host SEO spam (2007 disabled comment form) and dead ad code, so they go.
HTML_COMMENT = re.compile(r'<!--(?!\[if)(?:(?!-->).)*?<a\s(?:(?!-->).)*?-->', re.I | re.S)
SCRIPT_OR_STYLE = re.compile(r'(<(script|style)\b.*?</\2\s*>)', re.I | re.S)

# The CafePress "shop" (removed at the owner's request): the masthead cell and any other link.
SHOP_CELL = re.compile(r'<td\b[^>]*>\s*<img[^>]*header_deviders[^>]*>\s*</td>\s*<td\b[^>]*>\s*<div[^>]*>\s*(?:&nbsp;)?\s*'
                       r'<a\b[^>]*cafeshops[^>]*>.*?</a>\s*</div>\s*</td>', re.I | re.S)
SHOP_LINK = re.compile(r'<a\b[^>]*cafeshops\.com[^>]*>(.*?)</a\s*>', re.I | re.S)

# The Q&A "add your comment:" answer form (its fields only: the form also wraps the archives list).
QA_FORM = re.compile(r'<span[^>]*>\s*add\s*</span>\s*<span[^>]*>\s*your\s*</span>\s*<span[^>]*>\s*comment:\s*</span>'
                     r'\s*(?:<br\s*/?>)?\s*<form\b[^>]*>\s*<table\b(?:(?!</table).)*?name="comment"(?:(?!</table).)*?</table\s*>',
                     re.I | re.S)

# Newsletter sign-up boxes (removed at the owner's request; the list is long gone). Three shapes:
# the sign-up row heading every comments table, which comes with a colour bar and the (emptied)
# ad row before "comments:"; the "join the sixosix newsletter" boxes (div#email_submit*); and
# any innermost table row that holds the sign-up text with its email field (covers, front pages).
NEWSLETTER_ROWS = re.compile(r'<form name="email"(?:(?!</form).)*</form\s*>\s*<tr>\s*<td colspan="2" style="background-color:[^"]*'
                             r'height:\s*5px;?"\s*>\s*</td>\s*</tr>\s*<tr>\s*<td[^>]*>\s*ad\s*</td>(?:(?!<tr\b).)*', re.I | re.S)
NEWSLETTER_BOX = re.compile(r'<div\b[^>]*\bid="email_submit\d*"[^>]*>(?:(?!</div).)*</div\s*>', re.I | re.S)
NEWSLETTER_ROW = re.compile(r'<tr\b[^>]*>(?:(?!<tr\b|</tr).)*?(?:newsletter_header\.gif|newsletter(?:(?!<tr\b|</tr).)*?<input\b)'
                            r'(?:(?!<tr\b|</tr).)*</tr\s*>', re.I | re.S)

# PHP error output captured with pages (2004-2010): it names server paths and accounts.
PHP_ERROR = re.compile(r'(?:<br\s*/?>\s*)?<b>\s*(?:Warning|Fatal error|Parse error|Notice|Deprecated)\s*</b>\s*:'
                       r'[^\n]*?on line\s*<b>\s*\d+\s*</b>(?:\s*<br\s*/?>)?', re.I)

# Images loaded from other sites (dead 2004 buttons): they would send visitors' details there.
OFFSITE_IMG = re.compile(r'<img\b[^>]*\bsrc\s*=\s*["\']?\s*(?:https?:)?//(?![\w.-]*606mag\.com[:/"\'\s>])[^>]*>', re.I)

# The reader "post a comment:" form: comments are closed for good (removed at the owner's request).
COMMENT_FORM = re.compile(r'<form\b[^>]*>(?:(?!</form).)*?post a comment(?:(?!</form).)*?</form\s*>', re.I | re.S)

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
    doc, n = SHOP_CELL.subn('', doc)
    stats['shop links removed'] += n
    doc, n = SHOP_LINK.subn(lambda m: m.group(1), doc)
    stats['shop links removed'] += n
    doc, n = COMMENT_FORM.subn('', doc)
    stats['comment forms removed'] += n
    doc, n = QA_FORM.subn('', doc)
    stats['comment forms removed'] += n
    n = 0
    for rx in (NEWSLETTER_ROWS, NEWSLETTER_BOX, NEWSLETTER_ROW):
        doc, k = rx.subn('', doc)
        n += k
    stats['newsletter sign-ups removed'] += n
    doc, n = PHP_ERROR.subn('', doc)
    stats['php error messages removed'] += n
    doc, n = OFFSITE_IMG.subn('', doc)
    stats['off-site images removed'] += n
    doc, n = HIDDEN_LINK.subn('', doc)
    stats['hidden spam links stripped'] += n
    parts = SCRIPT_OR_STYLE.split(doc)            # leave <!-- --> wrappers inside code alone
    out = []
    for i in range(0, len(parts), 3):
        text, n = HTML_COMMENT.subn('', parts[i])
        stats['html comments with links stripped'] += n
        out.append(text)
        if i + 1 < len(parts):
            out.append(parts[i + 1])
    doc = ''.join(out)
    for rx in AD_MARKUP:
        doc, n = rx.subn('', doc)
        stats['ad-server elements stripped'] += n
    doc, n = strip_qa_spam(doc)
    stats['Q&A spam answers removed'] += n
    doc = anonymize_qa(doc)
    doc, removed, kept = strip_spam(doc)
    stats['spam comments removed'] += removed
    stats['reader comments kept'] += kept
    return doc
