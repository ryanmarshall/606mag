# sixosix · 606mag.com

Recovery and rebuild of **606mag.com** — *sixosix magazine*, a Chicago online magazine
published monthly through 2004 (12 issues, ~200 articles, photo essays, reader comments)
and kept online until 2015.

The original PHP/MySQL site was lost: a 2010 server migration broke it, and it was
compromised four times (2009, 2012, 2015, 2017) before the host disabled it. This
repository rebuilds it for posterity as a static site.

## Where the content came from

| Source | What it gave |
|---|---|
| Wayback Machine | 19,803 captures (2004–2015); latest *genuine* copy of every page |
| Common Crawl (20 crawls, 2008–2015) | raw article files and directory listings the Wayback missed |
| DreamHost server copy | 1,040 never-archived files: full photo galleries, newsletters, article pages |
| MySQL database (`sixosix`) | authoritative catalog, comments, Q&A, Sad Libs, "Going to Hell" |

Every downloaded file is verified against its archive's SHA-1 digest.

## Pipeline (`tools/`, Python 3 standard library only)

1. `build_manifest.py` — one entry per page with candidate captures, newest genuine first
   (defacement / parking / homepage-fallback / PHP-error captures are demoted or rejected).
2. `fetch.py` — resumable, throttle-tolerant downloader into a content-addressed store.
3. `cc_fetch_records.py`, `server_import.py` — merge Common Crawl and server-copy files
   (the as-published version always wins; the server only fills gaps).
4. `build_site.py` — static mirror: link rewriting, UTF-8, dead ad/tracker removal,
   comment-spam removal (`comments.py`, `curation.json`), security scan.
5. `malware_scan.py`, `inventory.py`, `catalog.py`, `dump_to_sqlite.py` — analysis.

## Not in this repository (by design)

The server copy (malware samples, credentials), the database dump (subscriber emails,
visitor IPs) and the raw capture store stay on the maintainer's machine.

## Status

- [x] Recovery from Wayback, Common Crawl, server copy and database
- [x] Cleaned static mirror of the original site
- [ ] Modern static site (Astro, TypeScript), faithful to the 2004 design, responsive
- [ ] Original mirror published under `/archive`
- [ ] Deploy to GitHub Pages
