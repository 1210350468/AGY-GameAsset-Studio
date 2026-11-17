set -euo pipefail

source "$(dirname "$0")/common.sh"

BLENDER_RELEASE=4.5.16
BLENDER_DIR="blender-${BLENDER_RELEASE}-linux-x64"
TOOLS="$DATA_ROOT/tools"
ARCHIVE="$TOOLS/${BLENDER_DIR}.tar.xz"
BINARY="$TOOLS/$BLENDER_DIR/blender"

mkdir -p "$TOOLS"
if [ ! -x "$BINARY" ]; then
  curl --fail --location --retry 4 --retry-delay 3 --continue-at - \
    --output "$ARCHIVE" \
    "https://download.blender.org/release/Blender4.5/${BLENDER_DIR}.tar.xz"
  tar -xJf "$ARCHIVE" -C "$TOOLS"
fi

"$BINARY" --background --factory-startup --python-expr 'import bpy; print("AGY Blender", bpy.app.version_string)'
announce "Blender installed: $BINARY"

