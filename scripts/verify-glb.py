import argparse
import json
from pathlib import Path

import trimesh
from pygltflib import GLTF2


parser = argparse.ArgumentParser(description="校验真实 GLB 游戏资源")
parser.add_argument("model", type=Path)
parser.add_argument("--require-skin", action="store_true")
args = parser.parse_args()

model = args.model.resolve(strict=True)
assert model.stat().st_size > 1024, "GLB 文件异常"
scene = trimesh.load(model, force="scene")
meshes = [mesh for mesh in scene.geometry.values() if isinstance(mesh, trimesh.Trimesh)]
faces = sum(len(mesh.faces) for mesh in meshes)
assert faces > 0, "模型缺少三角面"

gltf = GLTF2().load(str(model))
skins = len(gltf.skins)
joints = sum(len(skin.joints) for skin in gltf.skins)
if args.require_skin:
    assert skins > 0 and joints > 0, "模型缺少真实骨骼和蒙皮"

result = {
    "file": str(model),
    "bytes": model.stat().st_size,
    "meshes": len(meshes),
    "triangles": faces,
    "skins": skins,
    "joints": joints,
    "animations": len(gltf.animations),
    "bounds": scene.bounds.tolist(),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
