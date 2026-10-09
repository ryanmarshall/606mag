#!/bin/bash
# Pull Common Crawl index records for 606mag.com, retrying the slow index server.
cd "$(dirname "$0")"
for idx in CC-MAIN-2009-2010 CC-MAIN-2012; do
  for try in 1 2 3 4 5 6; do
    curl -s --max-time 240 "https://index.commoncrawl.org/$idx-index?url=606mag.com/*&output=json&limit=5000" > "cc_$idx.jsonl.tmp"
    if head -c 1 "cc_$idx.jsonl.tmp" | grep -q '{'; then
      mv "cc_$idx.jsonl.tmp" "cc_$idx.jsonl"; echo "$idx: $(wc -l < cc_$idx.jsonl) records (try $try)"; break
    fi
    echo "$idx: try $try failed ($(head -c 60 cc_$idx.jsonl.tmp | tr '\n' ' '))"; sleep $((try * 20))
  done
done
