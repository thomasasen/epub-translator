#!/usr/bin/env bash
# RunPod start command downloads this script; all state is stored below /workspace.
set -Eeuo pipefail
umask 027
BASE=/workspace/epub-translator
APP=$BASE/upstream
LOG=$BASE/logs
REF=${TBL_REF:-0cc31bc7f4aeedfcb3fe904eeaebd15d6fa0ad1f}
log() { echo "[$(date -u +%FT%TZ)] $*"; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "${EPUB_USERNAME:-}" && -n "${EPUB_PASSWORD:-}" ]] || die "Set EPUB_USERNAME and EPUB_PASSWORD in RunPod."
[[ "$EPUB_USERNAME" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Invalid EPUB_USERNAME."
[[ "$EPUB_PASSWORD" =~ ^.{12,}$ ]] || die "EPUB_PASSWORD needs >= 12 characters."
[[ -d /workspace ]] || die "Set RunPod volume mount path to /workspace."
command -v nvidia-smi >/dev/null || die "GPU image required (nvidia-smi missing)."
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sort -nr | head -1 | tr -d '[:space:]')
[[ "$VRAM" =~ ^[0-9]+$ ]] || die "GPU VRAM unreadable."
if [[ -n "${EPUB_MODEL:-}" ]]; then
  MODEL=$EPUB_MODEL
  CTX=${EPUB_CONTEXT:-8192}
elif ((VRAM >= 44000)); then
  MODEL=gemma4:31b-it-q8_0
  CTX=${EPUB_CONTEXT:-8192}
elif ((VRAM >= 22000)); then
  MODEL=gemma4:31b-it-qat
  CTX=${EPUB_CONTEXT:-4096}
else
  die "Only $VRAM MiB VRAM; choose a 24 GB or 48 GB GPU, or override EPUB_MODEL."
fi
[[ "$CTX" =~ ^[0-9]+$ ]] && ((CTX >= 2048)) || die "EPUB_CONTEXT must be >=2048."
mkdir -p "$BASE" "$LOG" "$BASE/ollama-models" "$BASE/translated_files"
log "GPU VRAM=$VRAM MiB, Ollama model=$MODEL, context=$CTX"

# Ensure the offline EPUB audit is present on the persistent volume.
curl -fsSL https://raw.githubusercontent.com/thomasasen/epub-translator/main/audit_epub.py \
  -o "$BASE/audit_epub.py"
python3 -m py_compile "$BASE/audit_epub.py"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends curl ca-certificates git python3 python3-venv python3-pip nginx apache2-utils >/dev/null
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
  sh /tmp/ollama-install.sh
fi
export OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=$BASE/ollama-models
export OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NO_CLOUD=1
ollama serve >"$LOG/ollama.log" 2>&1 &
PID_OLLAMA=$!
cleanup() {
  trap - EXIT INT TERM
  for p in "${PID_WEB:-}" "${PID_APP:-}" "${PID_OLLAMA:-}"; do
    if [[ -n "$p" ]]; then kill "$p" 2>/dev/null || true; fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

ready=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then ready=1; break; fi
  kill -0 "$PID_OLLAMA" 2>/dev/null || die "Ollama crashed: $LOG/ollama.log"
  sleep 2
done
((ready == 1)) || die "Ollama timed out."
if ! ollama show "$MODEL" >/dev/null 2>&1; then
  log "Downloading $MODEL to persistent volume ..."
  ollama pull "$MODEL"
fi

# Red-team check: force an actual inference instead of assuming a download means
# the model loads. Warn when it falls back to slow CPU offload.
log "Verifying GPU inference for $MODEL (first model load may take time) ..."
if ! EPUB_MODEL_NAME="$MODEL" EPUB_NUM_CTX="$CTX" python3 - <<'PY'
import json
import os
import urllib.request
payload = {
    "model": os.environ["EPUB_MODEL_NAME"],
    "prompt": "Translate exactly into German: The door is open.",
    "stream": False,
    "keep_alive": "30m",
    "options": {"num_ctx": int(os.environ["EPUB_NUM_CTX"])},
}
request = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=600) as response:
    result = json.load(response)
if not result.get("response", "").strip():
    raise SystemExit("Ollama returned an empty inference")
print("Ollama inference OK")
PY
then
  die "Model could not generate a response on this Pod. Check VRAM and $LOG/ollama.log"
fi
log "Model residency:"
ollama ps || true
if ! ollama ps | grep -q '100% GPU'; then
  log "WARNING: model is not reported as 100% GPU-resident. Performance may be much worse."
fi

if [[ ! -d "$APP/.git" ]]; then
  [[ ! -e "$APP" ]] || die "$APP exists and is not a git checkout."
  git clone -q --depth 1 https://github.com/hydropix/TranslateBooksWithLLMs.git "$APP"
fi
if [[ "$(git -C "$APP" rev-parse HEAD)" != "$REF" ]]; then
  git -C "$APP" fetch -q --depth 1 origin "$REF"
  git -C "$APP" checkout -q --detach FETCH_HEAD
fi
cd "$APP"
[[ -x .venv/bin/python ]] || python3 -m venv .venv
REQ_SHA=$(sha256sum requirements.txt | cut -d' ' -f1)
if [[ ! -f .venv/.requirements-sha ]] || [[ "$(< .venv/.requirements-sha)" != "$REQ_SHA" ]]; then
  log "Installing Python requirements ..."
  .venv/bin/python -m pip install --no-cache-dir -r requirements.txt >"$LOG/pip.log" 2>&1 ||
    { tail -n 50 "$LOG/pip.log" >&2; die "pip install failed."; }
  printf '%s\n' "$REQ_SHA" > .venv/.requirements-sha
fi

export HOST=127.0.0.1 PORT=5000 LLM_PROVIDER=ollama
export OLLAMA_API_ENDPOINT=http://127.0.0.1:11434/api/generate
export API_ENDPOINT=$OLLAMA_API_ENDPOINT DEFAULT_MODEL=$MODEL OUTPUT_DIR=$BASE/translated_files
export OLLAMA_NUM_CTX=$CTX AUTO_ADJUST_CONTEXT=false
export MAX_TOKENS_PER_CHUNK=${MAX_TOKENS_PER_CHUNK:-800}
export PARALLEL_TRANSLATIONS=1 REQUEST_TIMEOUT=900 DEBUG_MODE=false

# Nginx access control: web, API and WebSocket traffic all require Basic Auth.
printf '%s\n' "$EPUB_PASSWORD" | htpasswd -i -c -B /etc/nginx/.epub-users "$EPUB_USERNAME" >/dev/null
chown root:www-data /etc/nginx/.epub-users
chmod 640 /etc/nginx/.epub-users
unset EPUB_PASSWORD
cat >/etc/nginx/conf.d/epub.conf <<'NGINX'
server {
    listen 3000;
    server_name _;
    client_max_body_size 150m;
    auth_basic "EPUB Translator";
    auth_basic_user_file /etc/nginx/.epub-users;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
        proxy_buffering off;
    }
}
NGINX
nginx -t >/dev/null 2>&1 || die "nginx configuration failed."

.venv/bin/python translation_api.py >"$LOG/translator.log" 2>&1 &
PID_APP=$!
ready=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 http://127.0.0.1:5000/api/health >/dev/null; then ready=1; break; fi
  kill -0 "$PID_APP" 2>/dev/null || { tail -n 50 "$LOG/translator.log" >&2; die "Translation app crashed."; }
  sleep 2
done
((ready == 1)) || die "Translation app failed healthcheck."

nginx -g 'daemon off;' >"$LOG/nginx.log" 2>&1 &
PID_WEB=$!
sleep 2
kill -0 "$PID_WEB" 2>/dev/null || die "nginx crashed."
CODE=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/ || true)
[[ "$CODE" == 401 ]] || die "Auth failure: expected 401 without password, got $CODE."
log "READY: RunPod Connect -> HTTP port 3000; log in as $EPUB_USERNAME"
log "Never expose internal ports 5000 or 11434. Logs: $LOG"
wait -n "$PID_WEB" "$PID_APP" "$PID_OLLAMA" || true
die "A service terminated unexpectedly; check $LOG"
