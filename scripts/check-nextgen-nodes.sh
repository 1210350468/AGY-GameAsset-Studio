set -euo pipefail

source "$(dirname "$0")/common.sh"

COMFY_ROOT="$SOURCE_ROOT/ComfyUI-v0.37.4"
COMFY_PYTHON="$ENV_ROOT/anime_next/bin/python"
CPU_PORT=8191

test -f "$COMFY_ROOT/main.py"
test -x "$COMFY_PYTHON"

if curl -fsS --max-time 2 "http://127.0.0.1:$CPU_PORT/system_stats" > /dev/null; then
  echo 'CPU 专用的 ComfyUI 运行环境已启动'
  exit 0
fi

announce '启动 CPU 专用 ComfyUI，验证节点定义和权重注册'
CUDA_VISIBLE_DEVICES=-1 nohup "$COMFY_PYTHON" "$COMFY_ROOT/main.py" \
  --cpu --listen 127.0.0.1 --port "$CPU_PORT" --disable-auto-launch \
  > "$DATA_ROOT/logs/comfyui-nextgen-cpu.log" 2>&1 < /dev/null &
echo "$!" > "$DATA_ROOT/comfyui-nextgen-cpu.pid"

for count in $(seq 1 40); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$CPU_PORT/system_stats" > /dev/null; then
    echo "CPU ComfyUI 就绪：127.0.0.1:$CPU_PORT"
    exit 0
  fi
  sleep 1
done

tail -n 45 "$DATA_ROOT/logs/comfyui-nextgen-cpu.log"
exit 1
