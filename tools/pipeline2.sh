#!/bin/bash
# Second pass: merge the DreamHost server copy (gap-fill only; as published wins),
# resolve the new pages from the blob store, rebuild the site, and take inventory.
cd "$(dirname "$0")/.."
while pgrep -f "tools/pipeline.sh" >/dev/null; do sleep 30; done
SERVER="server-copy/extracted/606mag.com_DISABLED_FOR_MALWARE_SCRIPT_CONTACT_DREAMHOST_SUPPORT_cp"
python3 -I tools/build_manifest.py tools/cdx_all.json tools/manifest.json --cc tools/cc_records_*.json tools/server_records.json
python3 -I tools/fetch.py tools/manifest.json archive-raw --passes 2 > tools/fetch_server.log 2>&1
tail -1 tools/fetch_server.log
python3 -I tools/build_site.py tools/manifest.json archive-raw site tools/report.json
python3 -I tools/inventory.py tools/cdx_all.json archive-raw tools/inventory.json tools/cc_records_*.json --server "$SERVER"
