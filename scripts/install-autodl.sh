set -euo pipefail

source "$(dirname "$0")/common.sh"

TARGET="${1:-all}"
case "$TARGET" in
  all|api|anime|pixal3d|partcrafter|skintokens|godot) ;;
  *) echo "用法：bash scripts/install-autodl.sh [all|api|anime|pixal3d|partcrafter|skintokens|godot]" >&2; exit 2 ;;
esac

if [ "$TARGET" = all ]; then
  bash "$STUDIO_ROOT/scripts/download-models.sh" all
  for part in api anime pixal3d partcrafter skintokens godot; do
    bash "$STUDIO_ROOT/scripts/install-autodl.sh" "$part"
  done
  announce '所有安装步骤已经执行，开始检查 AutoDL 环境'
  bash "$STUDIO_ROOT/scripts/doctor.sh"
  exit 0
fi

announce "安装模块：$TARGET"

if [ "$TARGET" = godot ]; then
  bash "$STUDIO_ROOT/scripts/install-godot.sh"
  exit 0
fi

if [ "$TARGET" = api ]; then
  make_env api 3.11
  "$ENV_ROOT/api/bin/python" -m pip install --upgrade pip setuptools wheel
  "$ENV_ROOT/api/bin/python" -m pip install -e "$STUDIO_ROOT"
  "$ENV_ROOT/api/bin/python" -c 'from asset_studio.api import app; print(app.title)'
  touch "$INSTALL_ROOT/api"
  exit 0
fi

if [ "$TARGET" = anime ]; then
  make_env anime 3.11
  get_repo https://github.com/Comfy-Org/ComfyUI.git "$SOURCE_ROOT/ComfyUI-v0.29.2" v0.29.2 tags
  "$ENV_ROOT/anime/bin/python" -m pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
  "$ENV_ROOT/anime/bin/python" -m pip install -r "$SOURCE_ROOT/ComfyUI-v0.29.2/requirements.txt"
  "$ENV_ROOT/anime/bin/python" -m pip install "huggingface_hub[hf_xet]"
  mkdir -p "$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints"
  if [ ! -s "$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints/$MODEL_CHECKPOINT" ]; then
    if [ -s "$SOURCE_ROOT/ComfyUI/models/checkpoints/$MODEL_CHECKPOINT" ]; then
      ln -s "$SOURCE_ROOT/ComfyUI/models/checkpoints/$MODEL_CHECKPOINT" \
        "$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints/$MODEL_CHECKPOINT"
    else
      "$ENV_ROOT/anime/bin/hf" download IbarakiDouji/WAI-NSFW-illustrious-SDXL "$MODEL_CHECKPOINT" \
        --local-dir "$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints"
    fi
  fi
  test -s "$SOURCE_ROOT/ComfyUI-v0.29.2/models/checkpoints/$MODEL_CHECKPOINT"
  verify_torch "$ENV_ROOT/anime/bin/python"
  touch "$INSTALL_ROOT/anime"
  exit 0
fi

if [ "$TARGET" = pixal3d ]; then
  command -v nvcc >/dev/null 2>&1 || { echo 'Pixal3D 扩展需要 CUDA Toolkit nvcc，建议使用 CUDA 12.4 的 AutoDL 镜像。' >&2; exit 1; }
  if [ "$(id -u)" = 0 ]; then
    apt-get update
    apt-get install -y build-essential libjpeg-dev libgl1 libglib2.0-0 libegl1 libglu1-mesa
  else
    test -f /usr/include/jpeglib.h || { echo '缺少 libjpeg-dev 头文件。' >&2; exit 1; }
    ldconfig -p | grep -q libEGL.so.1 || { echo '缺少 EGL 运行库。' >&2; exit 1; }
  fi
  make_env pixal 3.10
  get_repo https://github.com/microsoft/TRELLIS.2.git "$SOURCE_ROOT/TRELLIS.2"
  get_repo https://github.com/TencentARC/Pixal3D.git "$SOURCE_ROOT/Pixal3D" master
  get_repo https://github.com/microsoft/MoGe.git "$SOURCE_ROOT/MoGe"
  "$ENV_ROOT/pixal/bin/python" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
  "$ENV_ROOT/pixal/bin/python" -m pip install --upgrade setuptools wheel ninja packaging
  "$ENV_ROOT/pixal/bin/python" -m pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless \
    trimesh transformers gradio==6.0.1 tensorboard pandas lpips zstandard \
    kornia timm
  "$ENV_ROOT/pixal/bin/python" -m pip install "$SOURCE_ROOT/MoGe"
  "$ENV_ROOT/pixal/bin/python" -m pip install -r "$STUDIO_ROOT/requirements/pixal3d.txt"

  get_repo https://github.com/NVlabs/nvdiffrast.git "$SOURCE_ROOT/nvdiffrast" v0.4.0 tags
  get_repo https://github.com/JeffreyXiang/nvdiffrec.git "$SOURCE_ROOT/nvdiffrec" renderutils
  get_repo https://github.com/JeffreyXiang/CuMesh.git "$SOURCE_ROOT/CuMesh"
  get_repo https://github.com/JeffreyXiang/cubvh.git \
    "$SOURCE_ROOT/CuMesh/third_party/cubvh" \
    ce92267a24ef6ad7d2c8ccbc2ae2c021a6597e70 commit
  get_repo https://github.com/JeffreyXiang/FlexGEMM.git "$SOURCE_ROOT/FlexGEMM"
  EIGEN_COMMIT=21e4582d1739107337a03460c81412981130373e
  EIGEN_DIR="$SOURCE_ROOT/TRELLIS.2/o-voxel/third_party/eigen"
  if [ ! -f "$EIGEN_DIR/Eigen/Core" ]; then
    mkdir -p "$EIGEN_DIR"
    curl --fail --location --retry 4 --retry-delay 3 \
      --output "$DATA_ROOT/source-archives/eigen-$EIGEN_COMMIT.tar.gz" \
      "https://codeload.github.com/eigen-mirror/eigen/tar.gz/$EIGEN_COMMIT"
    tar -xzf "$DATA_ROOT/source-archives/eigen-$EIGEN_COMMIT.tar.gz" --strip-components=1 -C "$EIGEN_DIR"
    test -f "$EIGEN_DIR/Eigen/Core"
  fi
  export CPATH="$EIGEN_DIR${CPATH:+:$CPATH}"
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-build-isolation "$SOURCE_ROOT/nvdiffrast"
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-build-isolation "$SOURCE_ROOT/nvdiffrec"
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-build-isolation "$SOURCE_ROOT/CuMesh"
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-build-isolation "$SOURCE_ROOT/FlexGEMM"
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-deps --no-build-isolation "$SOURCE_ROOT/TRELLIS.2/o-voxel"
  "$ENV_ROOT/pixal/bin/python" -m pip install flash-attn==2.7.3 --no-build-isolation

  export NATTEN_CUDA_ARCH="${NATTEN_CUDA_ARCH:-8.0}"
  export NATTEN_N_WORKERS="${NATTEN_N_WORKERS:-4}"
  "$ENV_ROOT/pixal/bin/python" -m pip install natten==0.21.0 --no-build-isolation
  UTILS3D_WHEEL="$DATA_ROOT/source-archives/utils3d-0.0.2-py3-none-any.whl"
  if [ ! -s "$UTILS3D_WHEEL" ]; then
    curl --fail --location --retry 4 --output "$UTILS3D_WHEEL" \
      https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl
  fi
  "$ENV_ROOT/pixal/bin/python" -m pip install --no-deps "$UTILS3D_WHEEL"
  verify_torch "$ENV_ROOT/pixal/bin/python"
  (cd "$SOURCE_ROOT/Pixal3D" && "$ENV_ROOT/pixal/bin/python" -c 'from pixal3d.pipelines import Pixal3DImageTo3DPipeline; import o_voxel; print("Pixal3D imports passed")')
  test -s "$MODEL_ROOT/Pixal3D/pipeline.json"
  touch "$INSTALL_ROOT/pixal3d"
  exit 0
fi

if [ "$TARGET" = partcrafter ]; then
  if [ "$(id -u)" = 0 ]; then
    apt-get update
    apt-get install -y libegl1 libegl1-mesa libgl1-mesa-dev libgl1 libglib2.0-0
  else
    ldconfig -p | grep -q libEGL.so.1 || { echo '缺少 EGL 运行库。' >&2; exit 1; }
  fi
  make_env parts 3.11
  get_repo https://github.com/wgsxm/PartCrafter.git "$SOURCE_ROOT/PartCrafter"
  "$ENV_ROOT/parts/bin/python" -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
  "$ENV_ROOT/parts/bin/python" -m pip install torch-cluster -f https://data.pyg.org/whl/torch-2.5.1+cu124.html
  "$ENV_ROOT/parts/bin/python" -m pip install -r "$SOURCE_ROOT/PartCrafter/settings/requirements.txt" -c "$STUDIO_ROOT/requirements/partcrafter-constraints.txt"
  verify_torch "$ENV_ROOT/parts/bin/python"
  (cd "$SOURCE_ROOT/PartCrafter" && "$ENV_ROOT/parts/bin/python" -c 'from src.pipelines.pipeline_partcrafter import PartCrafterPipeline; print("PartCrafter imports passed")')
  mkdir -p "$SOURCE_ROOT/PartCrafter/pretrained_weights"
  "$ENV_ROOT/parts/bin/hf" download wgsxm/PartCrafter --local-dir "$SOURCE_ROOT/PartCrafter/pretrained_weights/PartCrafter" --max-workers 4
  "$ENV_ROOT/parts/bin/hf" download briaai/RMBG-1.4 --local-dir "$SOURCE_ROOT/PartCrafter/pretrained_weights/RMBG-1.4" --max-workers 4
  test -s "$SOURCE_ROOT/PartCrafter/pretrained_weights/PartCrafter/model_index.json"
  test -s "$SOURCE_ROOT/PartCrafter/pretrained_weights/RMBG-1.4/config.json"
  touch "$INSTALL_ROOT/partcrafter"
  exit 0
fi

if [ "$TARGET" = skintokens ]; then
  command -v nvcc >/dev/null 2>&1 || { echo 'SkinTokens 扩展需要 CUDA Toolkit nvcc。' >&2; exit 1; }
  make_env rig 3.11
  get_repo https://github.com/VAST-AI-Research/SkinTokens.git "$SOURCE_ROOT/SkinTokens"
  "$ENV_ROOT/rig/bin/python" -m pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
  "$ENV_ROOT/rig/bin/python" -m pip install --upgrade pip setuptools wheel ninja packaging
  "$ENV_ROOT/rig/bin/python" -m pip install -r "$SOURCE_ROOT/SkinTokens/requirements.txt" -c "$STUDIO_ROOT/requirements/skintokens-constraints.txt"
  "$ENV_ROOT/rig/bin/python" -m pip install scipy==1.15.3
  FLASH_WHEEL="$DATA_ROOT/source-archives/flash_attn-2.7.4.post1+cu12torch2.6cxx11abiFALSE-cp311-cp311-linux_x86_64.whl"
  if [ ! -s "$FLASH_WHEEL" ]; then
    curl --fail --location --retry 4 --output "$FLASH_WHEEL" \
      'https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1%2Bcu12torch2.6cxx11abiFALSE-cp311-cp311-linux_x86_64.whl'
  fi
  "$ENV_ROOT/rig/bin/python" -m pip install --no-deps "$FLASH_WHEEL"
  (cd "$SOURCE_ROOT/SkinTokens" && "$ENV_ROOT/rig/bin/python" download.py --model)
  verify_torch "$ENV_ROOT/rig/bin/python"
  (cd "$SOURCE_ROOT/SkinTokens" && "$ENV_ROOT/rig/bin/python" demo.py --help >/dev/null)
  touch "$INSTALL_ROOT/skintokens"
  exit 0
fi

