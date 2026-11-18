set -euo pipefail

source "$(dirname "$0")/common.sh"

MODEL="${1:-anima}"
exec "$ENV_ROOT/api/bin/python" "$STUDIO_ROOT/scripts/select-nextgen-gpu.py" --model "$MODEL"
