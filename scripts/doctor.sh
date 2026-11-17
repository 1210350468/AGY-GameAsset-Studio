set -euo pipefail

source "$(dirname "$0")/common.sh"

announce 'AutoDL GPU 信息'
nvidia-smi
announce '已安装模块'
for name in api anime pixal3d partcrafter skintokens; do
  if [ -f "$INSTALL_ROOT/$name" ]; then
    echo "已安装 $name"
  else
    echo "尚未安装 $name"
  fi
done
announce '数据盘情况'
df -h "$DATA_ROOT"
announce 'API 状态'
if [ -f "$INSTALL_ROOT/api" ]; then
  "$ENV_ROOT/api/bin/python" -c 'from asset_studio.api import app; print("FastAPI", app.title)'
fi

