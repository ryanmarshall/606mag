#!/usr/bin/env python3
"""Find and classify reader comments in 606mag pages (shared by the site builder).

Policy (verified against the sixosix database): every genuine comment predates the
bot era, which began April 2006, and everything from then on is spam. Comments dated
before 2006-04-01 are kept unless they carry hard spam signals (pharma spam, CJK or
forum-markup link spam) or are hand-excluded in curation.json; later ones are dropped.
The broader content rules are only a fallback for undated comments.

Each comment is a table row: subject / date / name / comment, followed by a thin
separator row. A comment is spam when it carries pharmacy/porn/gambling terms; or
several outbound links (HTML or BBCode); or a linked name together with a link in
its text; or BBCode links at all (no reader of this site wrote forum markup); or
mostly CJK text (the 2007 shelving-rack spam wave); or a link with only a few words
of text; or commercial terms (weight loss, loans...) plus a link in the text or the
name; or a linked name with nothing but a teaser ("Play online", "View Pictures").
"""
import json, os, re
from datetime import datetime, timezone

BOT_ERA = datetime(2006, 4, 1, tzinfo=timezone.utc)
_CURATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'curation.json')
EXCLUSIONS = json.load(open(_CURATION))['comment_exclusions'] if os.path.exists(_CURATION) else []

COMMENT = re.compile(
    r'<tr>\s*<td[^>]*>\s*<span[^>]*>\s*subject\s*</span>\s*:(?P<body>(?:(?!</td>).)*?)</td>\s*</tr>'
    r'(?P<sep>\s*<tr>\s*<td[^>]*border:[^>]*>\s*&nbsp;\s*</td>\s*</tr>)?', re.I | re.S)
FIELD = re.compile(r'<span[^>]*>\s*(date|name|comment)\s*</span>\s*:', re.I)
SPAM_TERMS = re.compile(
    r'\b(viagra|cialis|levitra|phentermine|xanax|valium|tramadol|ambien|soma|propecia|'
    r'casino|poker|bingo|blackjack|roulette|porn\w*|hentai|x{3}|escort|scort|incest|'
    r'ringtones?|payday|mortgage|replica|cheap\s+\w+\s+online|buy\s+\w+\s+online)\b', re.I)
LINK = re.compile(r'<a\s[^>]*href\s*=\s*["\']?\s*(?:https?://|www\.)', re.I)
BBCODE_LINK = re.compile(r'\[url\s*[=\]]', re.I)
CJK_ENTITY = re.compile(r'&#(1[2-9]\d{3}|[2-5]\d{4}|6[0-5]\d{3});')   # U+3000-U+FFFF
TEASER = re.compile(r'(view|see|watch|play|check|visit|click)(\s+\S+){0,2}|nice|cool|great|good|thanks?',
                    re.I)
COMMERCIAL = re.compile(r'\b(weight\s*loss|diet|pills?|loans?|insurance|forex|rolex|'
                        r'watches|handbags|jewelry|pharmacy|meds|seo)\b', re.I)

def fields(body):
    parts = FIELD.split(body)
    out = {'subject': parts[0]}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].lower()] = parts[i + 1]
    return out

CJK_CHAR = re.compile(r'[\u3000-\u9fff\uac00-\ud7af]')
DOMAIN = re.compile(r'[\w-]+\.[a-z]{2,}', re.I)


def is_spam_fields(subject='', name='', link='', comment=''):
    """Classify one comment given its fields as text (HTML allowed in comment).
    `link` is the commenter's website (the database column, or the name's href)."""
    subject, name, link, comment = (x or '' for x in (subject, name, link, comment))
    visible = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', comment)).strip()
    links = (len(LINK.findall(comment)) + len(BBCODE_LINK.findall(comment))
             + len(re.findall(r'(?:https?://|www\.)\S', visible)))
    name_link = bool(DOMAIN.search(link))
    every = ' '.join((subject, name, link, comment))
    if SPAM_TERMS.search(re.sub(r'<[^>]+>', ' ', every)):
        return True
    if BBCODE_LINK.search(every) or len(CJK_ENTITY.findall(every)) + len(CJK_CHAR.findall(every)) >= 4:
        return True
    if links and len(visible.split()) <= 4:
        return True
    if (links or name_link) and COMMERCIAL.search(every):
        return True
    if name_link and TEASER.fullmatch(visible.strip(' .!')):
        return True
    return links >= 2 or (links >= 1 and name_link)


NAME_HREF = re.compile(r'<a\s[^>]*href\s*=\s*["\']?([^"\'\s>]+)', re.I)


def is_spam(body):
    """Classify one comment from a rendered page (see COMMENT)."""
    f = {k: (v.decode('latin-1') if isinstance(v, bytes) else v) for k, v in fields(body).items()}
    href = NAME_HREF.search(f.get('name', ''))
    return is_spam_fields(re.sub(r'<[^>]+>', ' ', f.get('subject', '')),
                          re.sub(r'<[^>]+>', ' ', f.get('name', '')),
                          href.group(1) if href else '', f.get('comment', ''))


PHARMA = re.compile(r'\b(viagra|cialis|levitra|tadalafil|sildenafil|phentermine|tramadol|xanax|valium|'
                    r'ambien|propecia|meridia|adipex|hydrocodone|vicodin|oxycontin|soma|ultram|'
                    r'fioricet|carisoprodol|desyrel|diazepam|alprazolam)\b', re.I)


def hard_spam(subject='', name='', link='', comment=''):
    """Spam signals strong enough for the human era (before April 2006). Plain
    topic words (bingo, casino, porn) are not used: the magazine wrote about all
    of them, and readers joked about drugs in subject lines."""
    visible = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', comment or ''))
    links = (LINK.search(comment or '') or BBCODE_LINK.search(comment or '')
             or re.search(r'(?:https?://|www\.)\S', visible))
    every = ' '.join(x or '' for x in (subject, name, link, comment))
    drugs = {m.group(0).lower() for m in PHARMA.finditer(visible)}
    return bool(PHARMA.search(re.sub(r'<[^>]+>', ' ', name or '')) or len(drugs) >= 2
                or (drugs and links) or BBCODE_LINK.search(every)
                or len(CJK_ENTITY.findall(every)) + len(CJK_CHAR.findall(every)) >= 4)


def excluded(name, comment):
    plain = lambda x: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', x or '')).strip()
    return any(plain(name) == e['name'] and plain(comment).startswith(e['starts']) for e in EXCLUSIONS)


def keep_comment(when, name='', comment='', subject='', link=''):
    """The one decision used everywhere. `when` is a datetime (or None if unknown)."""
    if excluded(name, comment):
        return False
    if when is not None:
        return when < BOT_ERA and not hard_spam(subject, name, link, comment)
    return not is_spam_fields(subject, name, link, comment)


def page_comment_date(body):
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', re.sub(r'<[^>]+>', ' ', fields(body).get('date', '')))
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
    except ValueError:
        return None


EMAIL_ADDR = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}', re.I)
PHONE = re.compile(r'\(?\b\d{3}\)?[ .-]*\d{3}[ .-]\d{4}\b')


def scrub(text):
    """Contact details typed into a comment: emails and phone numbers removed."""
    return PHONE.sub('[phone removed]', EMAIL_ADDR.sub('[email removed]', text))
ANCHOR = re.compile(r'<a\b[^>]*>(.*?)</a>', re.I | re.S)
NAME_FIELD = re.compile(r'(<span[^>]*>\s*name\s*</span>\s*:)(.*?)(?=<br|<span|$)', re.I | re.S)
TEXT_FIELD = re.compile(r'(<span[^>]*>\s*comment\s*</span>\s*:)(.*)$', re.I | re.S)
QA_NAME = re.compile(r'(\d{2}\.\d{2}\.\d{2}[^<]*?:\s*<span[^>]*>)(.*?)(</span>\s*says:)', re.I | re.S)


def names_only(fragment):
    """A commenter's identity reduced to the name they typed (decided 2026-10-09):
    links around the name are unwrapped and email addresses removed."""
    return EMAIL_ADDR.sub('[email removed]', ANCHOR.sub(lambda m: m.group(1), fragment))


SUBJECT_FIELD = re.compile(r'(<span[^>]*>\s*subject\s*</span>\s*:)(.*?)(?=<br|<span|$)', re.I | re.S)


def anonymize_comment(html):
    html = SUBJECT_FIELD.sub(lambda m: m.group(1) + scrub(m.group(2)), html)
    html = NAME_FIELD.sub(lambda m: m.group(1) + names_only(m.group(2)), html)
    return TEXT_FIELD.sub(lambda m: m.group(1) + scrub(m.group(2)), html)


QA_ANSWER = re.compile(r'<tr>\s*<td align="left">\s*(\d{2})\.(\d{2})\.(\d{2})[^<]*?:\s*<span[^>]*>(.*?)</span>\s*says:'
                       r'\s*</td>\s*</tr>\s*<tr>\s*<td[^>]*>(.*?)</td>\s*</tr>', re.I | re.S)


def strip_qa_spam(doc):
    """Q&A answers follow the comment policy: dated answers from the bot era (April
    2006 on) and hard spam are removed. Returns (doc, removed)."""
    removed = 0
    def sub(m):
        nonlocal removed
        mm, dd, yy, name, text = m.groups()
        try:
            when = datetime(2000 + int(yy), int(mm), int(dd), tzinfo=timezone.utc)
        except ValueError:
            when = None
        href = NAME_HREF.search(name)
        if keep_comment(when, re.sub(r'<[^>]+>', ' ', name), text, '', href.group(1) if href else ''):
            return m.group(0)
        removed += 1
        return ''
    return QA_ANSWER.sub(sub, doc), removed


def anonymize_qa(doc):
    """Q&A answer pages: names-only for each 'NAME says:' header, no emails in answers."""
    i = doc.find('answers:</span>')
    if i < 0:
        return doc
    tail = QA_NAME.sub(lambda m: m.group(1) + names_only(m.group(2)) + m.group(3), doc[i:])
    return doc[:i] + scrub(tail)


def strip_spam(doc):
    """Remove spam comments (and their separator rows). Returns (doc, removed, kept)."""
    removed = kept = 0
    def sub(m):
        nonlocal removed, kept
        body = m.group('body')
        f = fields(body)
        href = NAME_HREF.search(f.get('name', ''))
        if not keep_comment(page_comment_date(body), re.sub(r'<[^>]+>', ' ', f.get('name', '')),
                            f.get('comment', ''), re.sub(r'<[^>]+>', ' ', f.get('subject', '')),
                            href.group(1) if href else ''):
            removed += 1
            return ''
        kept += 1
        return anonymize_comment(m.group(0))
    return COMMENT.sub(sub, doc), removed, kept
