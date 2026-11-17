set -euo pipefail

source "$(dirname "$0")/common.sh"

GODOT_VERSION=4.7.2
GODOT_RELEASE="Godot_v${GODOT_VERSION}-stable_linux.x86_64"
GODOT_DIRECTORY="$DATA_ROOT/tools/godot-${GODOT_VERSION}"
GODOT_BINARY="$GODOT_DIRECTORY/$GODOT_RELEASE"
GODOT_ARCHIVE="$DATA_ROOT/source-archives/$GODOT_RELEASE.zip"

mkdir -p "$GODOT_DIRECTORY" "$DATA_ROOT/source-archives"
if [ ! -x "$GODOT_BINARY" ]; then
  if [ ! -s "$GODOT_ARCHIVE" ]; then
    curl --fail --location --retry 4 --retry-delay 3 \
      --output "$GODOT_ARCHIVE" \
      "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/${GODOT_RELEASE}.zip"
  fi
  unzip -t "$GODOT_ARCHIVE"
  unzip -o "$GODOT_ARCHIVE" -d "$GODOT_DIRECTORY"
  chmod +x "$GODOT_BINARY"
fi

"$GODOT_BINARY" --headless --version
announce "Godot installed: $GODOT_BINARY"
