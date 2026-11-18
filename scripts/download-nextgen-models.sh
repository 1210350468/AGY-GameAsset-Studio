set -euo pipefail

source "$(dirname "$0")/common.sh"

NEXT_COMFY_ROOT="$SOURCE_ROOT/ComfyUI-v0.37.4"
ANIMA_ROOT="$MODEL_ROOT/nextgen/Anima-2.9B"
QWEN_ROOT="$MODEL_ROOT/nextgen/Qwen-Image-2.1"
HF="$ENV_ROOT/downloads/bin/hf"

test -x "$HF"
test -f "$NEXT_COMFY_ROOT/main.py"

download_model() {
  local repository="$1"
  local filename="$2"
  local destination="$3"
  local category="$4"
  local stored_file="$destination/$filename"

  mkdir -p "$destination" "$NEXT_COMFY_ROOT/models/$category"
  if [ ! -s "$stored_file" ]; then
    "$HF" download "$repository" "$filename" --local-dir "$destination"
  fi
  test -s "$stored_file"
  ln -sfn "$stored_file" "$NEXT_COMFY_ROOT/models/$category/$(basename "$filename")"
  announce "权重已安装：$(basename "$filename")"
}

TARGET="${1:-all}"
case "$TARGET" in
  all|anima|qwen) ;;
  *) echo "用法：bash scripts/download-nextgen-models.sh [all|anima|qwen]" >&2; exit 2 ;;
esac

if [ "$TARGET" = all ] || [ "$TARGET" = anima ]; then
  download_model Gazingstars123/Anima-2.9B \
    Anima-2.9B-preview-v1.safetensors "$ANIMA_ROOT" diffusion_models
  download_model circlestone-labs/Anima \
    split_files/text_encoders/qwen_3_06b_base.safetensors "$ANIMA_ROOT" text_encoders
  download_model circlestone-labs/Anima \
    split_files/vae/qwen_image_vae.safetensors "$ANIMA_ROOT" vae
fi

if [ "$TARGET" = all ] || [ "$TARGET" = qwen ]; then
  download_model Comfy-Org/Qwen-Image-2.1 \
    diffusion_models/qwen_image_2.1_bf16.safetensors "$QWEN_ROOT" diffusion_models
  download_model Comfy-Org/Qwen-Image-2.1 \
    text_encoders/qwen3vl_8b_bf16.safetensors "$QWEN_ROOT" text_encoders
  download_model Comfy-Org/Qwen-Image-2.1 \
    vae/qwen_image_2.1_vae_bf16.safetensors "$QWEN_ROOT" vae
fi

announce '指定模型的下载与文件存在性检查完成'
