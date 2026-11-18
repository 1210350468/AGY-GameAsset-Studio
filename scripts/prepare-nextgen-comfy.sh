set -euo pipefail

source "$(dirname "$0")/common.sh"

NEXT_COMFY_VERSION=0.37.4
NEXT_COMFY_ROOT="$SOURCE_ROOT/ComfyUI-v${NEXT_COMFY_VERSION}"

announce '准备隔离的 ComfyUI 运行环境'
get_repo https://github.com/Comfy-Org/ComfyUI.git "$NEXT_COMFY_ROOT" "v${NEXT_COMFY_VERSION}" tags
make_env anime_next 3.11
"$ENV_ROOT/anime_next/bin/python" -m pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
  --index-url https://download.pytorch.org/whl/cu126
"$ENV_ROOT/anime_next/bin/python" -m pip install -r "$NEXT_COMFY_ROOT/requirements.txt"

mkdir -p "$NEXT_COMFY_ROOT/models/diffusion_models" \
  "$NEXT_COMFY_ROOT/models/text_encoders" \
  "$NEXT_COMFY_ROOT/models/vae" \
  "$NEXT_COMFY_ROOT/user"

"$ENV_ROOT/anime_next/bin/python" -m pip check
"$ENV_ROOT/anime_next/bin/python" -m compileall -q "$NEXT_COMFY_ROOT/comfy"
announce "ComfyUI ${NEXT_COMFY_VERSION} 环境就绪"
