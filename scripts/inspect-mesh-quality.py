import argparse
import json
from pathlib import Path

from asset_studio.quality import inspect_model


parser = argparse.ArgumentParser(description="统计 GLB 真实网格的结构完整性")
parser.add_argument("model", type=Path)
args = parser.parse_args()
print(json.dumps(inspect_model(args.model), ensure_ascii=False, indent=2))
