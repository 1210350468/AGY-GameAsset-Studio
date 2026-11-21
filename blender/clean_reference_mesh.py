import argparse
import json
import sys
from pathlib import Path

import bpy


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--remove-name", required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

source = Path(args.input).resolve(strict=True)
destination = Path(args.output).resolve()
if source == destination:
    raise ValueError("必须保留原始素材")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for existing in list(bpy.data.objects):
    bpy.data.objects.remove(existing, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=str(source))

original_skeletons = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
original_animations = [action.name for action in bpy.data.actions]
print("实际导入对象", [(obj.name, obj.type, len(obj.data.polygons) if obj.type == "MESH" else None) for obj in bpy.data.objects])
removed = [
    obj for obj in bpy.data.objects
    if obj.type == "MESH" and (
        obj.name == args.remove_name
        or obj.data.name == args.remove_name
        or (len(obj.data.polygons) <= 4 and max(obj.dimensions) >= 10)
    )
]
if len(removed) != 1:
    raise ValueError(f"指定的网格必须恰好存在一份：{args.remove_name}")
target = removed[0]
if target.find_armature() is not None or target.vertex_groups:
    raise ValueError("禁止删除蒙皮人物网格")
if len(target.data.polygons) > 4 or min(target.dimensions) > 0.02 or max(target.dimensions) < 10:
    raise ValueError("目标网格不符合独立大型平面特征")

removed_faces = len(target.data.polygons)
bpy.data.objects.remove(target, do_unlink=True)
if len([obj for obj in bpy.data.objects if obj.type == "ARMATURE"]) != len(original_skeletons):
    raise ValueError("人物骨骼丢失")

destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
for obj in bpy.data.objects:
    obj.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=str(destination),
    export_format="GLB",
    export_yup=True,
    export_animations=True,
    use_selection=True,
)
if not destination.is_file() or destination.stat().st_size == 0:
    raise FileNotFoundError("清理后 GLB 未生成")
print(json.dumps({
    "source": str(source),
    "output": str(destination),
    "removed_mesh": args.remove_name,
    "removed_faces": removed_faces,
    "original_actions": len(original_animations),
    "armatures": len(original_skeletons),
}, ensure_ascii=False))
