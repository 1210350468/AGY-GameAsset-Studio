import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--height-ratio", type=float, required=True)
parser.add_argument("--preserve-skin", action="store_true")
arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

if not 0.01 <= arguments.height_ratio <= 0.055:
    raise ValueError("脚底修复高度必须介于模型高度的 1% 至 5.5%")
source = Path(arguments.input).resolve(strict=True)
destination = Path(arguments.output).resolve()
if source == destination:
    raise ValueError("必须保留原始 GLB")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for existing in list(bpy.data.objects):
    bpy.data.objects.remove(existing, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=str(source))
meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
if armatures and not arguments.preserve_skin:
    raise ValueError("已绑定骨骼的怪物必须显式开启骨骼保留")
if arguments.preserve_skin and not armatures:
    raise ValueError("要求保留骨骼的模型实际缺少骨骼")
if arguments.preserve_skin:
    skinned_meshes = [item for item in meshes if item.find_armature() in armatures and item.vertex_groups]
    if len(skinned_meshes) != 1:
        raise ValueError("已绑定骨骼的模型需要恰好一个蒙皮网格")
    for item in meshes:
        if item not in skinned_meshes:
            bpy.data.objects.remove(item, do_unlink=True)
    meshes = skinned_meshes
if len(meshes) != 1:
    raise ValueError("脚底裁切只适用于单网格怪物模型")
obj = meshes[0]
if not obj.data.uv_layers or not obj.data.materials:
    raise ValueError("模型缺少需要保留的 UV 或材质")

world_points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
minimum = Vector((min(p[index] for p in world_points) for index in range(3)))
maximum = Vector((max(p[index] for p in world_points) for index in range(3)))
span = maximum - minimum
if span.z <= 0 or span.z < max(span.x, span.y) * 0.9:
    raise ValueError("模型不符合竖直站姿，无法确定脚底高度")
cut_z = minimum.z + span.z * arguments.height_ratio

original_faces = len(obj.data.polygons)
mesh = bmesh.new()
mesh.from_mesh(obj.data)
mesh.verts.ensure_lookup_table()
local_plane_point = obj.matrix_world.inverted() @ Vector((0, 0, cut_z))
local_plane_normal = obj.matrix_world.to_3x3().transposed() @ Vector((0, 0, 1))
bmesh.ops.bisect_plane(
    mesh,
    geom=list(mesh.verts) + list(mesh.edges) + list(mesh.faces),
    dist=0.000001,
    plane_co=local_plane_point,
    plane_no=local_plane_normal,
    clear_inner=True,
    clear_outer=False,
)
mesh.to_mesh(obj.data)
mesh.free()
obj.data.validate()
obj.data.update()
remaining_faces = len(obj.data.polygons)
if not 0.80 * original_faces < remaining_faces < original_faces:
    raise ValueError(f"脚底修复面数异常：{original_faces} → {remaining_faces}")

destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
if arguments.preserve_skin:
    for imported in bpy.data.objects:
        imported.select_set(True)
else:
    obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(
    filepath=str(destination), export_format="GLB", export_yup=True,
    use_selection=True,
)
if not destination.is_file() or destination.stat().st_size == 0:
    raise FileNotFoundError("修复后的 GLB 未生成")
print(json.dumps({
    "source": str(source),
    "destination": str(destination),
    "height_ratio": arguments.height_ratio,
    "cut_world_z": round(cut_z, 6),
    "original_faces": original_faces,
    "remaining_faces": remaining_faces,
    "removed_faces": original_faces - remaining_faces,
    "materials": len(obj.data.materials),
    "uv_layers": len(obj.data.uv_layers),
    "preserved_armatures": len(armatures),
}, ensure_ascii=False))
