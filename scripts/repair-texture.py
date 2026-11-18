import argparse
import json
from pathlib import Path

from asset_studio.texture_repair import repair_opaque_atlas


parser = argparse.ArgumentParser(description="修复 GLB 的透明纹理图集引起的黑色残留")
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
print(json.dumps(repair_opaque_atlas(args.input, args.output), ensure_ascii=False, indent=2))
