from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from pygltflib import GLTF2
from scipy.ndimage import distance_transform_edt


def _surface_samples(mesh: trimesh.Trimesh, texture: np.ndarray) -> dict:
    if mesh.visual.uv is None or len(mesh.visual.uv) != len(mesh.vertices):
        raise ValueError("GLB 的 UV 坐标不完整")
    face_ids = np.linspace(0, len(mesh.faces) - 1, min(200000, len(mesh.faces)), dtype=np.int64)
    triangles = mesh.faces[face_ids]
    coordinates = mesh.visual.uv[triangles].mean(axis=1)
    px = np.clip((coordinates[:, 0] * (texture.shape[1] - 1)).astype(int), 0, texture.shape[1] - 1)
    py = np.clip(((1 - coordinates[:, 1]) * (texture.shape[0] - 1)).astype(int), 0, texture.shape[0] - 1)
    sampled = texture[py, px]
    points = mesh.vertices[triangles].mean(axis=1)
    lower_limit = mesh.bounds[0, 1] + 0.37 * (mesh.bounds[1, 1] - mesh.bounds[0, 1])
    lower = points[:, 1] < lower_limit

    def metrics(values: np.ndarray) -> dict:
        if not len(values):
            raise ValueError("模型位置分布异常，无法检查下半身贴图")
        return {
            "faces_sampled": int(len(values)),
            "transparent_texture_ratio": round(float(np.mean(values[:, 3] < 64)), 5),
            "dark_texture_ratio": round(float(np.mean(np.max(values[:, :3], axis=1) < 35)), 5),
        }

    return {"overall": metrics(sampled), "lower_body": metrics(sampled[lower])}


def repair_opaque_atlas(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    if source == destination.resolve():
        raise ValueError("必须将纹理修复结果写入独立模型文件")
    gltf = GLTF2().load(str(source))
    if gltf.skins:
        raise ValueError("当前 UV 纹理修复需要未绑定骨骼的模型，避免破坏蒙皮数据")
    if len(gltf.meshes) != 1 or len(gltf.materials) != 1 or gltf.materials[0].alphaMode != "OPAQUE":
        raise ValueError("此操作适用于单一网格且贴图材质采用 OPAQUE 的角色")

    scene = trimesh.load(source, force="scene")
    if len(scene.geometry) != 1:
        raise ValueError("需要一组连续的角色网格")
    mesh = next(iter(scene.geometry.values()))
    material = mesh.visual.material
    if material.baseColorTexture is None:
        raise ValueError("模型缺少基础色贴图")

    original = np.asarray(material.baseColorTexture.convert("RGBA"))
    before = _surface_samples(mesh, original)
    if before["lower_body"]["transparent_texture_ratio"] < 0.01:
        raise ValueError("模型下半身未检测到明显的透明纹理取样异常")

    repaired = original.copy()
    valid = original[:, :, 3] >= 250
    if float(np.mean(valid)) < 0.2:
        raise ValueError("贴图有效像素过少，无法进行可靠的边缘颜色扩展")
    indices = distance_transform_edt(~valid, return_distances=False, return_indices=True)
    missing = ~valid
    repaired[:, :, :3][missing] = original[indices[0][missing], indices[1][missing], :3]
    repaired[:, :, 3] = 255
    after = _surface_samples(mesh, repaired)
    if after["lower_body"]["transparent_texture_ratio"] > 0:
        raise ValueError("贴图修复后仍存在透明纹理采样区域")

    material.baseColorTexture = Image.fromarray(repaired, mode="RGBA")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scene.export(destination, file_type="glb")
    result = trimesh.load(destination, force="scene")
    if len(result.geometry) != 1:
        raise ValueError("导出的模型网格数量发生变化")
    actual = next(iter(result.geometry.values()))
    if len(actual.faces) != len(mesh.faces) or not np.allclose(result.bounds, scene.bounds, atol=0.0001):
        raise ValueError("贴图修复导致模型几何结构改变")
    exported = np.asarray(actual.visual.material.baseColorTexture.convert("RGBA"))
    final = _surface_samples(actual, exported)
    if final["lower_body"]["transparent_texture_ratio"] > 0:
        raise ValueError("GLB 重新导出后仍存在透明图集采样")

    return {
        "source": str(source),
        "output": str(destination),
        "method": "根据有效贴图像素扩展 UV 图集颜色，保留 GLB 原有三角网格",
        "texture_size": list(original.shape[:2][::-1]),
        "faces": len(mesh.faces),
        "before": before,
        "after": final,
    }
