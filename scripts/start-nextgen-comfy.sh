set -euo pipefail

source "$(dirname "$0")/common.sh"

COMFY_ROOT="$SOURCE_ROOT/ComfyUI-v0.37.4"
COMFY_PYTHON="$ENV_ROOT/anime_next/bin/python"
MODEL="${1:-anima}"
case "$MODEL" in
  anima) COMFY_PORT="${ASSET_STUDIO_ANIMA_PORT:-8189}"; OTHER_MODEL=qwen ;;
  qwen) COMFY_PORT="${ASSET_STUDIO_QWEN_PORT:-8190}"; OTHER_MODEL=anima ;;
  *) echo '请指定 anima 或 qwen' >&2; exit 2 ;;
esac

test -f "$COMFY_ROOT/main.py"
test -x "$COMFY_PYTHON"
mkdir -p "$DATA_ROOT/comfy-nextgen-$MODEL/input" "$DATA_ROOT/comfy-nextgen-$MODEL/output" "$DATA_ROOT/comfy-nextgen-$MODEL/user"

if curl -fsS --max-time 3 "http://127.0.0.1:$COMFY_PORT/system_stats" >/dev/null; then
  echo "新版 ComfyUI 已在端口 $COMFY_PORT 运行"
  exit 0
fi

OTHER_PORT=8190
if [ "$OTHER_MODEL" = anima ]; then OTHER_PORT=8189; fi
EXCLUDE_ARGS=()
if curl -fsS --max-time 3 "http://127.0.0.1:$OTHER_PORT/system_stats" >/dev/null && [ -s "$DATA_ROOT/nextgen-${OTHER_MODEL}-gpu" ]; then
  EXCLUDE_ARGS+=(--exclude "$(cat "$DATA_ROOT/nextgen-${OTHER_MODEL}-gpu")")
fi
GPU_INDEX="$($ENV_ROOT/api/bin/python "$STUDIO_ROOT/scripts/select-nextgen-gpu.py" --model "$MODEL" "${EXCLUDE_ARGS[@]}")"

announce "启动 $MODEL ComfyUI，使用 GPU$GPU_INDEX，端口 $COMFY_PORT"
CUDA_VISIBLE_DEVICES="$GPU_INDEX" nohup "$COMFY_PYTHON" "$COMFY_ROOT/main.py" \
  --listen 127.0.0.1 --port "$COMFY_PORT" --disable-auto-launch --lowvram --cpu-vae \
  --database-url "sqlite:///$DATA_ROOT/comfy-nextgen-$MODEL.sqlite" \
  --user-directory "$DATA_ROOT/comfy-nextgen-$MODEL/user" \
  --input-directory "$DATA_ROOT/comfy-nextgen-$MODEL/input" \
  --output-directory "$DATA_ROOT/comfy-nextgen-$MODEL/output" \
  > "$DATA_ROOT/logs/comfyui-nextgen-$MODEL.log" 2>&1 < /dev/null &
echo "$!" > "$DATA_ROOT/comfyui-nextgen-${MODEL}.pid"
echo "$GPU_INDEX" > "$DATA_ROOT/nextgen-${MODEL}-gpu"

for count in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$COMFY_PORT/system_stats" > /dev/null; then
    announce '新版 ComfyUI 已启动'
    exit 0
  fi
  sleep 1
done

tail -n 45 "$DATA_ROOT/logs/comfyui-nextgen-$MODEL.log"
exit 1
