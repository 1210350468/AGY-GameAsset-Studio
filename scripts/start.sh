set -euo pipefail

source "$(dirname "$0")/common.sh"

test -x "$ENV_ROOT/api/bin/python" || { echo '请先运行 bash scripts/install-autodl.sh api' >&2; exit 1; }

if [ -f "$INSTALL_ROOT/anime" ]; then
  if ! curl -fsS --max-time 3 'http://127.0.0.1:8188/system_stats' >/dev/null; then
    announce '启动本地 ComfyUI'
    nohup "$ENV_ROOT/anime/bin/python" "$SOURCE_ROOT/ComfyUI/main.py" \
      --listen 127.0.0.1 --port 8188 --disable-auto-launch \
      > "$DATA_ROOT/logs/comfyui.log" 2>&1 < /dev/null &
    echo "$!" > "$DATA_ROOT/comfyui.pid"
  fi
fi

if ! curl -fsS --max-time 3 'http://127.0.0.1:18333/health' >/dev/null; then
  announce '启动游戏资产工作台 API'
  cd "$STUDIO_ROOT"
  nohup "$ENV_ROOT/api/bin/python" -m uvicorn asset_studio.api:app \
    --host "${ASSET_STUDIO_HOST:-127.0.0.1}" --port "${ASSET_STUDIO_PORT:-18333}" \
    > "$DATA_ROOT/logs/api.log" 2>&1 < /dev/null &
  echo "$!" > "$DATA_ROOT/api.pid"
fi

for count in $(seq 1 45); do
  if curl -fsS --max-time 3 'http://127.0.0.1:18333/health' >/dev/null; then
    announce '工作台启动成功：127.0.0.1:18333'
    exit 0
  fi
  sleep 1
done

tail -n 60 "$DATA_ROOT/logs/api.log"
exit 1

