#!/usr/bin/env bash
#
# Pull JSON exports from ecoNET API legacy endpoints.
# Usage: ./pull_exports.sh <label>
#   e.g. ./pull_exports.sh before
#        ./pull_exports.sh after
#
# Outputs go to exports/<label>_<timestamp>/ as pretty-printed JSON files.
#
# Credentials: set ECONET_PASS env var, or create .econet_credentials in
# this directory with the password on the first line.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_FILE="${SCRIPT_DIR}/.econet_credentials"

ECONET_HOST="${ECONET_HOST:-192.168.1.6}"
ECONET_USER="${ECONET_USER:-admin}"

if [[ -z "${ECONET_PASS:-}" ]]; then
    if [[ -f "$CREDS_FILE" ]]; then
        ECONET_PASS="$(head -n 1 "$CREDS_FILE")"
    else
        echo -n "EcoNet password: "
        read -rs ECONET_PASS
        echo
    fi
fi

LABEL="${1:?Usage: $0 <label>  (e.g. 'before' or 'after')}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="${SCRIPT_DIR}/../exports/${LABEL}_${TIMESTAMP}"

mkdir -p "$OUT_DIR"

BASE_URL="http://${ECONET_HOST}/econet"
AUTH="${ECONET_USER}:${ECONET_PASS}"

ENDPOINTS="regParams editParams sysParams"

ok_count=0
skip_count=0

echo "Pulling from ${ECONET_HOST} → ${OUT_DIR}"
echo ""

for endpoint in $ENDPOINTS; do
    echo -n "  ${endpoint}... "
    HTTP_CODE=$(curl -s -w "%{http_code}" -o "${OUT_DIR}/${endpoint}.json" \
        --user "$AUTH" \
        --max-time 15 \
        "${BASE_URL}/${endpoint}" 2>/dev/null || echo "000")

    if [[ "$HTTP_CODE" == "200" ]]; then
        python3 -m json.tool "${OUT_DIR}/${endpoint}.json" > "${OUT_DIR}/${endpoint}_pretty.json" 2>/dev/null \
            && mv "${OUT_DIR}/${endpoint}_pretty.json" "${OUT_DIR}/${endpoint}.json"
        size=$(wc -c < "${OUT_DIR}/${endpoint}.json" | tr -d ' ')
        echo "OK (${size} bytes)"
        ok_count=$((ok_count + 1))
    else
        rm -f "${OUT_DIR}/${endpoint}.json"
        echo "SKIP (HTTP ${HTTP_CODE})"
        skip_count=$((skip_count + 1))
    fi

    # Small delay between requests to avoid overwhelming the controller
    sleep 1
done

echo ""
echo "Done: ${ok_count} OK, ${skip_count} skipped"
echo "Saved to: ${OUT_DIR}"
echo ""
ls -la "${OUT_DIR}"
