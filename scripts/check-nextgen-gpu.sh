set -euo pipefail

source "$(dirname "$0")/common.sh"

GPU_INDEX=1
MINIMUM_MIB=50000
AVAILABLE_MIB="$(nvidia-smi --id="$GPU_INDEX" --query-gpu=memory.free --format=csv,noheader,nounits | tr -d '[:space:]')"
echo "GPU ${GPU_INDEX} 当前空闲显存：${AVAILABLE_MIB} MiB，启动要求：${MINIMUM_MIB} MiB"
if [ "$AVAILABLE_MIB" -lt "$MINIMUM_MIB" ]; then
  echo "GPU 推理暂未启动：当前显存不足" >&2
  exit 1
fi
echo 'GPU 显存保护检查通过'
