import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--target-faces", type=int, required=True)
parser.add_argument("--weld-distance", type=float, default=0.000001)
parser.add_argument("--max-texture-side", type=int, default=0)
parser.add_argument("--face-overshoot", type=float, default=1.05)
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

# 对角色和静态模型统一执行减面，保留 Armature、顶点权重和原始材质。
if total_triangles > arguments.target_faces:
    fraction = arguments.target_faces / total_triangles
    for obj in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if len(obj.data.polygons) < 20:
            continue
        if arguments.weld_distance > 0:
            mesh_data = bmesh.new()
            mesh_data.from_mesh(obj.data)
            bmesh.ops.remove_doubles(
                mesh_data,
                verts=list(mesh_data.verts),
                dist=arguments.weld_distance,
            )
            mesh_data.to_mesh(obj.data)
            mesh_data.free()
            obj.data.update()
        modifier = obj.modifiers.new(name="GameAssetDecimate", type="DECIMATE")
        modifier.ratio = max(0.001, fraction)
        obj.modifiers.move(len(obj.modifiers) - 1, 0)
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

    obj.data.validate()
    obj.data.update()

output_triangles = sum(sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons) for obj in meshes)
for attempt in range(4):
    if output_triangles <= arguments.target_faces * 1.05:
        break
    # 不规则网格的初次减面比例可能与实际面数不一致，需要再按实际面数调整。
    ratio = max(0.001, min(0.95, arguments.target_faces / output_triangles * 0.9))
    for obj in meshes:
        if len(obj.data.polygons) < 20:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        modifier = obj.modifiers.new(name=f"GameAssetFaceBudget{attempt + 1}", type="DECIMATE")
        modifier.ratio = ratio
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.data.validate()
        obj.data.update()
    output_triangles = sum(sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons) for obj in meshes)
if arguments.max_texture_side > 0:
    for image in bpy.data.images:
        width, height = image.size
        if max(width, height) <= arguments.max_texture_side:
            continue
        scale = arguments.max_texture_side / max(width, height)
        image.scale(max(1, round(width * scale)), max(1, round(height * scale)))

if output_triangles > arguments.target_faces * arguments.face_overshoot:
    raise RuntimeError(f"模型超过面数要求：{output_triangles} > {arguments.target_faces}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(destination), export_format="GLB", export_yup=True)

if not destination.is_file() or destination.stat().st_size == 0:
    raise RuntimeError("Blender 未生成有效文件")

print(json.dumps({
    "input": str(source),
    "output": str(destination),
    "meshes": len(meshes),
    "input_triangles": total_triangles,
    "output_triangles": output_triangles,
    "rigged": has_armature,
    "output_bytes": destination.stat().st_size,
}, ensure_ascii=False))

