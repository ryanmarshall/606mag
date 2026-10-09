#!/bin/bash
# Query every pre-hack Common Crawl index for 606mag.com, retrying the flaky index server.
cd "$(dirname "$0")"
for idx in $(tail -1 cc_crawls.txt); do
  [ -s "cc_$idx.jsonl" ] && head -c 1 "cc_$idx.jsonl" | grep -q '{' && { echo "$idx: cached $(wc -l < cc_$idx.jsonl)"; continue; }
  got=""
  for try in 1 2 3 4 5 6 7 8; do
    code=$(curl -s --max-time 300 -o "cc_$idx.tmp" -w "%{http_code}" "https://index.commoncrawl.org/$idx-index?url=606mag.com/*&output=json")
    if [ "$code" = "200" ] && head -c 1 "cc_$idx.tmp" | grep -q '{'; then
      mv "cc_$idx.tmp" "cc_$idx.jsonl"; got="$(wc -l < cc_$idx.jsonl | tr -d ' ') records"; break
    elif [ "$code" = "404" ]; then
      rm -f "cc_$idx.tmp"; : > "cc_$idx.none"; got="0 records"; break
    fi
    sleep $((try * 30))
  done
  echo "$idx: ${got:-FAILED after retries}"
done
rm -f cc_*.tmp
