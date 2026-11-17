import argparse
import json
import sys
from pathlib import Path

import bpy


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--target-faces", type=int, required=True)
arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

source = Path(arguments.input).resolve(strict=True)
destination = Path(arguments.output).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(source))

meshes = [item for item in bpy.data.objects if item.type == "MESH"]
if not meshes:
    raise RuntimeError("输入文件没有 Mesh")

total_triangles = sum(sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons) for obj in meshes)
has_armature = any(item.type == "ARMATURE" for item in bpy.data.objects)

# 保留角色的骨骼、蒙皮与动画。未绑定骨骼的静态网格执行减面。
if not has_armature and total_triangles > arguments.target_faces:
    fraction = arguments.target_faces / total_triangles
    for obj in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if len(obj.data.polygons) < 20:
            continue
        modifier = obj.modifiers.new(name="GameAssetDecimate", type="DECIMATE")
        modifier.ratio = max(0.001, fraction)
        bpy.ops.object.modifier_apply(modifier=modifier.name)

for obj in meshes:
    if not obj.data.uv_layers:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(destination), export_format="GLB", export_yup=True)

if not destination.is_file() or destination.stat().st_size == 0:
    raise RuntimeError("Blender 未生成有效文件")

print(json.dumps({
    "input": str(source),
    "output": str(destination),
    "meshes": len(meshes),
    "input_triangles": total_triangles,
    "rigged": has_armature,
    "output_bytes": destination.stat().st_size,
}, ensure_ascii=False))

