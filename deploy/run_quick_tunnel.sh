#!/usr/bin/env bash
set -euo pipefail

URL_FILE=/opt/maispopular/data/webapp_url.txt
mkdir -p "$(dirname "$URL_FILE")"

/usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8031 --no-autoupdate 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line"
  if [[ "$line" =~ https://[-a-zA-Z0-9]+\.trycloudflare\.com ]]; then
    url="${BASH_REMATCH[0]}"
    tmp="${URL_FILE}.tmp.$$"
    printf '%s\n' "$url" > "$tmp"
    chmod 600 "$tmp"
    mv -f "$tmp" "$URL_FILE"
    printf 'Mini App URL synchronized.\n'
  fi
done
