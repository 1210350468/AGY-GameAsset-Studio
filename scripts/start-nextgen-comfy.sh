set -euo pipefail

source "$(dirname "$0")/common.sh"

COMFY_ROOT="$SOURCE_ROOT/ComfyUI-v0.37.4"
COMFY_PYTHON="$ENV_ROOT/anime_next/bin/python"
COMFY_PORT="${ASSET_STUDIO_NEXTGEN_PORT:-8189}"

test -f "$COMFY_ROOT/main.py"
test -x "$COMFY_PYTHON"

if curl -fsS --max-time 3 "http://127.0.0.1:$COMFY_PORT/system_stats" >/dev/null; then
  echo "新版 ComfyUI 已在端口 $COMFY_PORT 运行"
  exit 0
fi

bash "$STUDIO_ROOT/scripts/check-nextgen-gpu.sh"

announce "启动独立 ComfyUI，新版模型使用 GPU1，端口 $COMFY_PORT"
CUDA_VISIBLE_DEVICES=1 nohup "$COMFY_PYTHON" "$COMFY_ROOT/main.py" \
  --listen 127.0.0.1 --port "$COMFY_PORT" --disable-auto-launch \
  > "$DATA_ROOT/logs/comfyui-nextgen.log" 2>&1 < /dev/null &
echo "$!" > "$DATA_ROOT/comfyui-nextgen.pid"

for count in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$COMFY_PORT/system_stats" > /dev/null; then
    announce '新版 ComfyUI 已启动'
    exit 0
  fi
  sleep 1
done

tail -n 45 "$DATA_ROOT/logs/comfyui-nextgen.log"
exit 1
