set -euo pipefail

STUDIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$STUDIO_ROOT/.env" ]; then
  set -a
  source "$STUDIO_ROOT/.env"
  set +a
fi

if [ -x "$HOME/.local/bin/uv" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if [ -x "$HOME/anaconda3/bin/conda" ]; then
  export PATH="$HOME/anaconda3/bin:$PATH"
fi
if [ -n "${CUDA_HOME:-}" ]; then
  export PATH="$CUDA_HOME/bin:$PATH"
elif [ -x /usr/local/cuda-12.4/bin/nvcc ]; then
  export CUDA_HOME=/usr/local/cuda-12.4
  export PATH="$CUDA_HOME/bin:$PATH"
fi
if [ -n "${CUDA_HOME:-}" ]; then
  export CUDACXX="$CUDA_HOME/bin/nvcc"
  export CUDAToolkit_ROOT="$CUDA_HOME"
  export CMAKE_CUDA_COMPILER="$CUDACXX"
fi

DATA_ROOT="${ASSET_STUDIO_DATA_ROOT:-/root/autodl-tmp/agy-game-asset-studio}"
SOURCE_ROOT="$DATA_ROOT/sources"
ENV_ROOT="$DATA_ROOT/envs"
INSTALL_ROOT="$DATA_ROOT/installed"
MODEL_ROOT="$DATA_ROOT/models"
MODEL_CHECKPOINT="${ASSET_STUDIO_IMAGE_CHECKPOINT:-waiIllustriousSDXL_v170.safetensors}"

export HF_HOME="$DATA_ROOT/cache/huggingface"
export TORCH_HOME="$DATA_ROOT/cache/torch"
export HF_ENDPOINT="${ASSET_STUDIO_HF_ENDPOINT:-${HF_ENDPOINT:-https://hf-mirror.com}}"
export PIP_CACHE_DIR="$DATA_ROOT/cache/pip"
export XDG_CACHE_HOME="$DATA_ROOT/cache/xdg"
export TMPDIR="$DATA_ROOT/scratch"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
export TORCH_EXTENSIONS_DIR="$DATA_ROOT/cache/torch_extensions"
export UV_CACHE_DIR="$DATA_ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$DATA_ROOT/python"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0}"

mkdir -p "$SOURCE_ROOT" "$MODEL_ROOT" "$ENV_ROOT" "$INSTALL_ROOT" "$HF_HOME" "$TORCH_HOME" "$PIP_CACHE_DIR" "$XDG_CACHE_HOME" "$TMPDIR" "$TORCH_EXTENSIONS_DIR" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$DATA_ROOT/logs"

if ! command -v uv >/dev/null 2>&1 && ! command -v conda >/dev/null 2>&1; then
  echo '部署环境需要 uv 或 Conda。' >&2
  exit 1
fi

make_env() {
  local name="$1"
  local py_version="$2"
  if [ ! -x "$ENV_ROOT/$name/bin/python" ]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv --seed --python "$py_version" "$ENV_ROOT/$name"
    else
      conda create -y --override-channels -c https://repo.anaconda.com/pkgs/main -p "$ENV_ROOT/$name" "python=$py_version"
    fi
  fi
}

get_repo() {
  local url="$1"
  local target="$2"
  local ref="${3:-main}"
  local ref_type="${4:-heads}"
  local repository="${url#https://github.com/}"
  repository="${repository%.git}"
  local archive="$DATA_ROOT/source-archives/$(basename "$target")-${ref}.tar.gz"
  local archive_url="https://codeload.github.com/$repository/tar.gz/refs/$ref_type/$ref"
  if [ "$ref_type" = commit ]; then
    archive_url="https://codeload.github.com/$repository/tar.gz/$ref"
  fi
  if [ -f "$target/.source-ready" ]; then
    return
  fi
  mkdir -p "$DATA_ROOT/source-archives" "$target"
  curl --fail --location --retry 4 --retry-delay 3 \
    --output "$archive" \
    "$archive_url"
  tar -xzf "$archive" --strip-components=1 -C "$target"
  touch "$target/.source-ready"
}

verify_torch() {
  local python_bin="$1"
  "$python_bin" -c 'import torch; assert torch.cuda.is_available(), "CUDA initialization failed"; print("CUDA", torch.version.cuda, "GPU", torch.cuda.get_device_name(0))'
}

announce() {
  echo "[$(date -Is)] $*"
}

