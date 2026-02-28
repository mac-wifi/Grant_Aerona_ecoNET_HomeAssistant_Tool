#!/usr/bin/env bash
#
# Pull JSON exports from all 3 ecoNET API endpoints.
# Usage: ./pull_exports.sh <label>
#   e.g. ./pull_exports.sh before
#        ./pull_exports.sh after
#
# Outputs go to exports/<label>/ as timestamped JSON files.

set -euo pipefail

ECONET_HOST="${ECONET_HOST:-192.168.1.6}"
ECONET_USER="${ECONET_USER:-admin}"

if [[ -z "${ECONET_PASS:-}" ]]; then
    echo -n "EcoNet password: "
    read -rs ECONET_PASS
    echo
fi

LABEL="${1:?Usage: $0 <label>  (e.g. 'before' or 'after')}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/../exports/${LABEL}_${TIMESTAMP}"

mkdir -p "$OUT_DIR"

BASE_URL="http://${ECONET_HOST}/econet"
AUTH="${ECONET_USER}:${ECONET_PASS}"

for endpoint in regParams editParams sysParams; do
    echo -n "Fetching ${endpoint}... "
    HTTP_CODE=$(curl -s -w "%{http_code}" -o "${OUT_DIR}/${endpoint}.json" \
        --user "$AUTH" \
        --max-time 15 \
        "${BASE_URL}/${endpoint}")

    if [[ "$HTTP_CODE" == "200" ]]; then
        python3 -m json.tool "${OUT_DIR}/${endpoint}.json" > "${OUT_DIR}/${endpoint}_pretty.json" 2>/dev/null \
            && mv "${OUT_DIR}/${endpoint}_pretty.json" "${OUT_DIR}/${endpoint}.json"
        echo "OK ($(wc -c < "${OUT_DIR}/${endpoint}.json" | tr -d ' ') bytes)"
    else
        echo "FAILED (HTTP ${HTTP_CODE})"
    fi
done

echo ""
echo "Exports saved to: ${OUT_DIR}"
echo "Files:"
ls -la "${OUT_DIR}"
