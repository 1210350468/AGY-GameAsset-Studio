import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


arguments = sys.argv[sys.argv.index("--") + 1:]
parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args(arguments)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(options.input.resolve(strict=True)))
objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
if not objects:
    raise RuntimeError("导入的 GLB 缺少三维网格")

corners = [item.matrix_world @ Vector(corner) for item in objects for corner in item.bound_box]
minimum = Vector(tuple(min(vertex[axis] for vertex in corners) for axis in range(3)))
maximum = Vector(tuple(max(vertex[axis] for vertex in corners) for axis in range(3)))
center = (minimum + maximum) / 2
size = maximum - minimum
if min(size.x, size.y, size.z) <= 0:
    raise RuntimeError("模型边界尺寸无效")

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (1, 1, 1)
scene.display.shading.show_shadows = False
scene.display.shading.show_cavity = False

camera_data = bpy.data.cameras.new("AppearanceInspectionCamera")
camera = bpy.data.objects.new("AppearanceInspectionCamera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.type = "ORTHO"
camera_data.ortho_scale = max(size.z * 1.18, size.x * 1.5, size.y * 1.5)
options.output.mkdir(parents=True, exist_ok=True)

radius = max(size) * 3
for azimuth in range(0, 360, 45):
    angle = math.radians(azimuth)
    camera.location = center + Vector((radius * math.sin(angle), -radius * math.cos(angle), 0))
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(options.output / f"silhouette_{azimuth:03d}.png")
    bpy.ops.render.render(write_still=True)
    if not Path(scene.render.filepath).is_file():
        raise RuntimeError(f"轮廓渲染输出缺失：{azimuth}")

print(f"完成 {len(range(0, 360, 45))} 个实际三维模型投影视角")
