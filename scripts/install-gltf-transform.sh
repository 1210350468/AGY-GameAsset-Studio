set -euo pipefail

source "$(dirname "$0")/common.sh"

NODE_ENV="$ENV_ROOT/node22"
GLTF_TOOLS="$DATA_ROOT/tools/gltf-transform"
GLTF_CLI="$GLTF_TOOLS/node_modules/@gltf-transform/cli/bin/cli.js"

make_env downloads 3.11
"$ENV_ROOT/downloads/bin/python" -m pip install nodeenv==1.12.0

if [ ! -x "$NODE_ENV/bin/node" ]; then
  "$ENV_ROOT/downloads/bin/nodeenv" --node=22.15.0 --with-npm "$NODE_ENV"
fi
export PATH="$NODE_ENV/bin:$PATH"

if [ ! -f "$GLTF_CLI" ]; then
  npm install --prefix "$GLTF_TOOLS" @gltf-transform/cli@4.5.0
fi
node "$GLTF_CLI" help resize > /dev/null
node "$GLTF_CLI" help meshopt > /dev/null
announce 'glTF Transform 4.5.0 已安装，支持纹理缩放与 Meshopt 压缩'
