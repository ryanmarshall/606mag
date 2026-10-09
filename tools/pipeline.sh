#!/bin/bash
# Finish the recovery: wait for downloads, merge Common Crawl, fetch homepage history,
# and rebuild the static site.
cd "$(dirname "$0")/.."
while pgrep -f "tools/fetch.py tools/manifest.json archive-raw --passes 8" >/dev/null; do sleep 60; done
echo "main download finished: $(tail -1 tools/fetch.log)"
while pgrep -f "cc_query_all.sh" >/dev/null; do sleep 60; done
for f in tools/cc_CC-MAIN-*.jsonl; do
  idx=$(basename "$f" .jsonl); idx=${idx#cc_}
  python3 -I tools/cc_fetch_records.py "$f" archive-raw "tools/cc_records_$idx.json"
done
python3 -I tools/build_manifest.py tools/cdx_all.json tools/manifest.json --cc tools/cc_records_*.json
python3 -I tools/fetch.py tools/manifest.json archive-raw --passes 3 --history '^/(main\.php)?$' > tools/history.log 2>&1
grep -E "history pass|FINISHED" tools/history.log
python3 -I tools/build_site.py tools/manifest.json archive-raw site tools/report.json
