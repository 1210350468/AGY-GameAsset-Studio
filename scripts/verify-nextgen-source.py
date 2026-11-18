import argparse
import ast
import json
from pathlib import Path


parser = argparse.ArgumentParser(description="检查新版 ComfyUI 官方节点源码定义")
parser.add_argument("--source", type=Path, required=True)
args = parser.parse_args()

root = args.source.resolve(strict=True)
requirements = {
    "nodes.py": {
        "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "EmptyLatentImage",
        "KSampler", "VAEDecode", "SaveImage", "LoadImage",
    },
    "comfy_extras/nodes_qwen.py": {"TextEncodeQwenImage21"},
    "comfy/supported_models.py": {"Anima"},
}

verified = {}
for filename, classes in requirements.items():
    source = root / filename
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    declared = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    missing = classes - declared
    if missing:
        raise RuntimeError(f"新版 ComfyUI 源码缺少节点：{filename} {sorted(missing)}")
    verified[filename] = sorted(classes)

print(json.dumps({"source": str(root), "verified": verified}, ensure_ascii=False, indent=2))
