import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


parser = argparse.ArgumentParser()
parser.add_argument("model", type=Path)
args = parser.parse_args()

scene = trimesh.load(args.model.resolve(strict=True), force="scene")
if len(scene.geometry) != 1:
    raise ValueError("当前材质分析需要单一网格")
mesh = next(iter(scene.geometry.values()))
uv = mesh.visual.uv
image = np.asarray(mesh.visual.material.baseColorTexture.convert("RGBA"))
face_count = len(mesh.faces)
indices = np.random.default_rng(20261119).choice(face_count, min(200000, face_count), replace=False)
faces = mesh.faces[indices]
midpoints = mesh.vertices[faces].mean(axis=1)
sample_uv = uv[faces].mean(axis=1)
pixel_x = np.clip((sample_uv[:, 0] * (image.shape[1] - 1)).astype(int), 0, image.shape[1] - 1)
pixel_y = np.clip(((1 - sample_uv[:, 1]) * (image.shape[0] - 1)).astype(int), 0, image.shape[0] - 1)
colors = image[pixel_y, pixel_x]
height = mesh.bounds[1, 1] - mesh.bounds[0, 1]

results = {}
for name, condition in {
    "all": np.ones(len(indices), dtype=bool),
    "lower": midpoints[:, 1] < mesh.bounds[0, 1] + 0.37 * height,
    "middle": (midpoints[:, 1] >= mesh.bounds[0, 1] + 0.37 * height) & (midpoints[:, 1] < mesh.bounds[0, 1] + 0.7 * height),
    "upper": midpoints[:, 1] >= mesh.bounds[0, 1] + 0.7 * height,
}.items():
    sample = colors[condition]
    results[name] = {
        "faces_sampled": int(len(sample)),
        "transparent_texel_ratio": round(float(np.mean(sample[:, 3] < 64)), 5),
        "dark_texel_ratio": round(float(np.mean(np.max(sample[:, :3], axis=1) < 35)), 5),
        "semi_transparent_texel_ratio": round(float(np.mean(sample[:, 3] < 250)), 5),
    }

print(json.dumps({"model": str(args.model), "material_alpha_mode": "OPAQUE", "regions": results}, ensure_ascii=False, indent=2))
