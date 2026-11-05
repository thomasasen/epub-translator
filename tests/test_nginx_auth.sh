#!/usr/bin/env bash
# End-to-end regression for isolated nginx Basic Auth.
# Intended for GitHub Actions ubuntu-latest; requires sudo and network for apt.
set -Eeuo pipefail

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx apache2-utils >/dev/null

sudo mkdir -p /etc/nginx
python3 - <<'PY' | sudo tee /etc/nginx/epub-translator.conf >/dev/null
from pathlib import Path
source = Path("bootstrap.sh").read_text()
header = "cat >/etc/nginx/epub-translator.conf <<'NGINX'\n"
start = source.index(header) + len(header)
end = source.index("\nNGINX", start)
print(source[start:end])
PY

printf '%s\n' 'integration-password-123456' | sudo htpasswd -i -c -B \
  /etc/nginx/.epub-users integration >/dev/null
sudo chown root:www-data /etc/nginx/.epub-users
sudo chmod 640 /etc/nginx/.epub-users
sudo -u www-data test -r /etc/nginx/.epub-users
sudo nginx -t -c /etc/nginx/epub-translator.conf

# Local fake backend: keeps this test independent of GPU, Ollama and Flask.
python3 -m http.server 5000 --bind 127.0.0.1 >/tmp/epub-test-backend.log 2>&1 &
backend=$!
sudo nginx -c /etc/nginx/epub-translator.conf
cleanup() {
  sudo nginx -s stop -c /etc/nginx/epub-translator.conf 2>/dev/null || true
  kill "$backend" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 30); do
  if curl -fsS -u integration:integration-password-123456 http://127.0.0.1:3000/ >/dev/null 2>&1; then break; fi
  sleep 1
done
expect_status() {
  local expected=$1
  shift
  local received
  received=$(curl -sS -o /dev/null -w '%{http_code}' "$@" http://127.0.0.1:3000/)
  if [[ "$received" != "$expected" ]]; then
    echo "HTTP Basic Auth regression: expected $expected, got $received" >&2
    exit 1
  fi
}
expect_status 401
expect_status 401 -u integration:wrong-password
expect_status 200 -u integration:integration-password-123456
echo "Nginx Basic Auth integration PASS: anonymous=401, wrong=401, correct=200"
