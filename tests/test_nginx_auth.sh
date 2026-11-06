#!/usr/bin/env bash
# Real Nginx integration test for public proxy with no additional password.
set -Eeuo pipefail
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx >/dev/null
python3 - <<'PY' | sudo tee /etc/nginx/epub-translator.conf >/dev/null
from pathlib import Path
s = Path("bootstrap.sh").read_text()
begin = "cat >/etc/nginx/epub-translator.conf <<'NGINX'\n"
start = s.index(begin) + len(begin)
print(s[start:s.index("\nNGINX", start)])
PY
sudo nginx -t -c /etc/nginx/epub-translator.conf
tmp=$(mktemp -d)
mkdir -p "$tmp/audiobook"
echo '{"ok": true}' >"$tmp/audiobook/health"
python3 -m http.server 5000 --bind 127.0.0.1 >/tmp/epub-test-translation.log 2>&1 &
translation=$!
(cd "$tmp" && python3 -m http.server 5100 --bind 127.0.0.1) >/tmp/epub-test-audio.log 2>&1 &
audio=$!
sudo nginx -c /etc/nginx/epub-translator.conf
cleanup() {
  sudo nginx -s stop -c /etc/nginx/epub-translator.conf 2>/dev/null || true
  kill "$translation" "$audio" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then break; fi
  sleep 1
done
expect() {
  local status=$1
  local url=$2
  local actual
  actual=$(curl -s -o /dev/null -w '%{http_code}' "$url")
  [[ "$actual" == "$status" ]] || { echo "$url expected $status got $actual" >&2; exit 1; }
}
expect 200 http://127.0.0.1:3000/
expect 200 http://127.0.0.1:3000/audiobook/health
expect 200 http://127.0.0.1:3000/audiobook/
echo "Nginx proxy integration PASS: translator and audiobook work without Basic Auth"
