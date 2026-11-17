set -euo pipefail

source "$(dirname "$0")/common.sh"

TARGET="${1:-all}"
case "$TARGET" in
  all|anime|pixal3d|partcrafter|skintokens) ;;
  *) echo "用法：bash scripts/download-models.sh [all|anime|pixal3d|partcrafter|skintokens]" >&2; exit 2 ;;
esac

if [ "$TARGET" = all ]; then
  for model in anime pixal3d partcrafter skintokens; do
    bash "$STUDIO_ROOT/scripts/download-models.sh" "$model"
  done
  exit 0
fi

make_env downloads 3.11
"$ENV_ROOT/downloads/bin/python" -m pip install 'huggingface_hub[hf_xet]>=0.36,<1'
HF="$ENV_ROOT/downloads/bin/hf"

announce "下载模型与权重：$TARGET"

if [ "$TARGET" = anime ]; then
  destination="$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints"
  mkdir -p "$destination"
  if [ ! -s "$destination/$MODEL_CHECKPOINT" ]; then
    if [ -s "$SOURCE_ROOT/ComfyUI/models/checkpoints/$MODEL_CHECKPOINT" ]; then
      ln -s "$SOURCE_ROOT/ComfyUI/models/checkpoints/$MODEL_CHECKPOINT" "$destination/$MODEL_CHECKPOINT"
    else
      "$HF" download IbarakiDouji/WAI-NSFW-illustrious-SDXL "$MODEL_CHECKPOINT" --local-dir "$destination"
    fi
  fi
  test -s "$destination/$MODEL_CHECKPOINT"
  exit 0
fi

if [ "$TARGET" = pixal3d ]; then
  "$HF" download TencentARC/Pixal3D --local-dir "$MODEL_ROOT/Pixal3D" --max-workers 4
  "$HF" download camenduru/dinov3-vitl16-pretrain-lvd1689m --max-workers 4
  "$HF" download Ruicheng/moge-2-vitl --max-workers 4
  "$HF" download ZhengPeng7/BiRefNet --max-workers 4
  cp "$STUDIO_ROOT/config/pixal-pipeline.json" "$MODEL_ROOT/Pixal3D/pipeline.json"

  get_repo https://github.com/valeoai/NAF.git "$SOURCE_ROOT/NAF" main heads
  mkdir -p "$TORCH_HOME/hub/checkpoints"
  if [ ! -e "$TORCH_HOME/hub/valeoai_NAF_main" ]; then
    ln -s "$SOURCE_ROOT/NAF" "$TORCH_HOME/hub/valeoai_NAF_main"
  fi
  if [ ! -s "$TORCH_HOME/hub/checkpoints/naf_release.pth" ]; then
    curl --fail --location --retry 5 --retry-delay 3 --connect-timeout 20 \
      --output "$TORCH_HOME/hub/checkpoints/naf_release.pth" \
      https://github.com/valeoai/NAF/releases/download/model/naf_release.pth
  fi
  test -s "$MODEL_ROOT/Pixal3D/pipeline.json"
  test -s "$MODEL_ROOT/Pixal3D/ckpts/ss_flow_img_dit_1_3B_64_bf16.safetensors"
  test -s "$MODEL_ROOT/Pixal3D/ckpts/slat_flow_img2shape_dit_1_3B_1024_bf16.safetensors"
  test -s "$MODEL_ROOT/Pixal3D/ckpts/slat_flow_imgshape2tex_dit_1_3B_1024_bf16.safetensors"
  test -s "$TORCH_HOME/hub/checkpoints/naf_release.pth"
  exit 0
fi

if [ "$TARGET" = partcrafter ]; then
  get_repo https://github.com/wgsxm/PartCrafter.git "$SOURCE_ROOT/PartCrafter"
  "$HF" download wgsxm/PartCrafter --local-dir "$SOURCE_ROOT/PartCrafter/pretrained_weights/PartCrafter" --max-workers 4
  "$HF" download briaai/RMBG-1.4 --local-dir "$SOURCE_ROOT/PartCrafter/pretrained_weights/RMBG-1.4" --max-workers 4
  test -s "$SOURCE_ROOT/PartCrafter/pretrained_weights/PartCrafter/model_index.json"
  test -s "$SOURCE_ROOT/PartCrafter/pretrained_weights/PartCrafter/transformer/diffusion_pytorch_model.safetensors"
  test -s "$SOURCE_ROOT/PartCrafter/pretrained_weights/RMBG-1.4/model.safetensors"
  exit 0
fi

if [ "$TARGET" = skintokens ]; then
  get_repo https://github.com/VAST-AI-Research/SkinTokens.git "$SOURCE_ROOT/SkinTokens"
  "$HF" download VAST-AI/SkinTokens experiments/skin_vae_2_10_32768/last.ckpt --local-dir "$SOURCE_ROOT/SkinTokens"
  "$HF" download VAST-AI/SkinTokens experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt --local-dir "$SOURCE_ROOT/SkinTokens"
  "$HF" download Qwen/Qwen3-0.6B --exclude '*.safetensors' '*.bin' --local-dir "$SOURCE_ROOT/SkinTokens/models/Qwen3-0.6B"
  test -s "$SOURCE_ROOT/SkinTokens/experiments/skin_vae_2_10_32768/last.ckpt"
  test -s "$SOURCE_ROOT/SkinTokens/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt"
fi
