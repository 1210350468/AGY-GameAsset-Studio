set -euo pipefail

STUDIO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$STUDIO_ROOT/.env" ]; then
  set -a
  source "$STUDIO_ROOT/.env"
  set +a
fi

DATA_ROOT="${ASSET_STUDIO_DATA_ROOT:-/root/autodl-tmp/agy-game-asset-studio}"
SOURCE_ROOT="$DATA_ROOT/sources"
ENV_ROOT="$DATA_ROOT/envs"
INSTALL_ROOT="$DATA_ROOT/installed"
MODEL_CHECKPOINT="${ASSET_STUDIO_IMAGE_CHECKPOINT:-waiIllustriousSDXL_v170.safetensors}"

export HF_HOME="$DATA_ROOT/cache/huggingface"
export XDG_CACHE_HOME="$DATA_ROOT/cache/xdg"
export TMPDIR="$DATA_ROOT/scratch"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
export TORCH_EXTENSIONS_DIR="$DATA_ROOT/cache/torch_extensions"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.9}"

mkdir -p "$SOURCE_ROOT" "$ENV_ROOT" "$INSTALL_ROOT" "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR" "$TORCH_EXTENSIONS_DIR" "$DATA_ROOT/logs"

if ! command -v conda >/dev/null 2>&1; then
  echo 'AutoDL 实例需要先安装 Conda，并在 shell 中启用 conda 命令。' >&2
  exit 1
fi

make_env() {
  local name="$1"
  local py_version="$2"
  if [ ! -x "$ENV_ROOT/$name/bin/python" ]; then
    conda create -y -p "$ENV_ROOT/$name" "python=$py_version"
  fi
}

get_repo() {
  local url="$1"
  local target="$2"
  local ref="${3:-}"
  if [ ! -d "$target/.git" ]; then
    if [ -n "$ref" ]; then
      git clone --recursive --branch "$ref" "$url" "$target"
    else
      git clone --recursive "$url" "$target"
    fi
  fi
}

verify_torch() {
  local python_bin="$1"
  "$python_bin" -c 'import torch; assert torch.cuda.is_available(), "CUDA initialization failed"; print("CUDA", torch.version.cuda, "GPU", torch.cuda.get_device_name(0))'
}

announce() {
  echo "[$(date -Is)] $*"
}

