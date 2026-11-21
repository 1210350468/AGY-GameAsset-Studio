from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def inspect_ground_artifacts(source: Path) -> dict:
    scene = trimesh.load(source, force="scene", process=False)
    geometries = [mesh for mesh in scene.geometry.values() if isinstance(mesh, trimesh.Trimesh)]
    if len(geometries) != 1:
        raise ValueError("地面残留分析要求一个未绑定骨骼的独立网格")
    mesh = geometries[0]
    if mesh.is_empty:
        raise ValueError("原模型没有有效三角形")

    merged = mesh.copy()
    merged.merge_vertices(merge_tex=True, merge_norm=True)
    adjacent = merged.face_adjacency
    graph = coo_matrix(
        (np.ones(len(adjacent), dtype=np.int8), (adjacent[:, 0], adjacent[:, 1])),
        shape=(len(merged.faces), len(merged.faces)),
    ).tocsr()
    component_count, labels = connected_components(graph, directed=False)
    counts = np.bincount(labels, minlength=component_count)
    largest = int(counts.argmax())

    triangles = merged.triangles
    centers = triangles.mean(axis=1)
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = np.linalg.norm(cross, axis=1) * 0.5
    horizontal = np.abs(cross[:, 1]) >= 0.93 * np.maximum(np.linalg.norm(cross, axis=1), 1e-12)
    minimum, maximum = merged.bounds
    span = maximum - minimum
    if np.any(span <= 0):
        raise ValueError("模型空间尺寸异常")
    ground_band = centers[:, 1] < minimum[1] + span[1] * 0.055
    horizontal_ground_area = float(areas[ground_band & horizontal].sum())
    footprint_area = float(span[0] * span[2])
    ground_area_ratio = horizontal_ground_area / footprint_area
    patch_faces = np.flatnonzero(ground_band & horizontal)
    patch_index = np.full(len(merged.faces), -1, dtype=np.int32)
    patch_index[patch_faces] = np.arange(len(patch_faces))
    patch_adjacency = patch_index[adjacent]
    patch_adjacency = patch_adjacency[np.all(patch_adjacency >= 0, axis=1)]
    patch_graph = coo_matrix(
        (np.ones(len(patch_adjacency), dtype=np.int8),
         (patch_adjacency[:, 0], patch_adjacency[:, 1])),
        shape=(len(patch_faces), len(patch_faces)),
    ).tocsr()
    patch_count, patch_labels = connected_components(patch_graph, directed=False)
    patch_areas = np.bincount(patch_labels, weights=areas[patch_faces], minlength=patch_count)
    top_patch_ids = np.argsort(patch_areas)[-5:][::-1]
    top_patches = []
    for patch_id in top_patch_ids:
        selected = patch_faces[patch_labels == patch_id]
        patch_center = centers[selected]
        delta = patch_center.max(axis=0) - patch_center.min(axis=0)
        top_patches.append({
            "faces": int(len(selected)),
            "area": round(float(patch_areas[patch_id]), 6),
            "footprint_ratio": round(float(patch_areas[patch_id] / footprint_area), 5),
            "spans": np.round(delta, 5).tolist(),
            "width_ratio": round(float(delta[0] / span[0]), 5),
            "depth_ratio": round(float(delta[2] / span[2]), 5),
            "min_height_ratio": round(float((patch_center[:, 1].min() - minimum[1]) / span[1]), 5),
        })

    comp_min = np.full((component_count, 3), np.inf)
    comp_max = np.full((component_count, 3), -np.inf)
    for axis in range(3):
        np.minimum.at(comp_min[:, axis], labels, centers[:, axis])
        np.maximum.at(comp_max[:, axis], labels, centers[:, axis])
    comp_span = comp_max - comp_min
    comp_area = np.bincount(labels, weights=areas, minlength=component_count)
    comp_flat = np.bincount(labels, weights=areas * horizontal, minlength=component_count)
    comp_low = np.bincount(labels, weights=areas * ground_band, minlength=component_count)

    # 装备表面、鞋底和地面可能共享高度；仅选择整个连通部分都表现为低矮、宽阔平板的情况。
    plate = (
        (np.arange(component_count) != largest)
        & (counts >= 100)
        & (comp_span[:, 1] < span[1] * 0.10)
        & (comp_min[:, 1] < minimum[1] + span[1] * 0.08)
        & (comp_span[:, 0] > span[0] * 0.32)
        & (comp_span[:, 2] > span[2] * 0.10)
        & (comp_span[:, 0] * comp_span[:, 2] > footprint_area * 0.06)
        & (comp_flat / np.maximum(comp_area, 1e-12) > 0.50)
        & (comp_low / np.maximum(comp_area, 1e-12) > 0.50)
    )
    plate_ids = np.flatnonzero(plate)
    removed_faces = int(counts[plate_ids].sum())
    return {
        "source": str(source),
        "faces": int(len(mesh.faces)),
        "components": int(component_count),
        "largest_component_faces": int(counts[largest]),
        "ground_horizontal_area": round(horizontal_ground_area, 6),
        "ground_footprint_area_ratio": round(ground_area_ratio, 5),
        "top_horizontal_patches": top_patches,
        "ground_anomaly_detected": bool(ground_area_ratio > 0.075 or len(plate_ids)),
        "detached_plates": int(len(plate_ids)),
        "removable_faces": removed_faces,
        "removable_face_ratio": round(removed_faces / len(mesh.faces), 5),
        "candidate_component_ids": plate_ids.tolist(),
        "candidate_faces": np.flatnonzero(np.isin(labels, plate_ids)),
    }


def remove_detached_ground(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if source == destination:
        raise ValueError("原始 GLB 必须保留，清理后的模型需另存")
    report = inspect_ground_artifacts(source)
    if not report["candidate_component_ids"]:
        raise ValueError("未检测到可安全独立移除的地面连通部分")
    if report["removable_face_ratio"] > 0.10:
        raise ValueError("检测出的地面连通部分过大，需要重新生成模型")
    scene = trimesh.load(source, force="scene", process=False)
    mesh = next(iter(scene.geometry.values()))
    face_mask = np.ones(len(mesh.faces), dtype=bool)
    face_mask[report["candidate_faces"]] = False
    mesh.update_faces(face_mask)
    mesh.remove_unreferenced_vertices()
    destination.parent.mkdir(parents=True, exist_ok=True)
    scene.export(destination, file_type="glb")
    if not destination.is_file():
        raise FileNotFoundError("地面清理后未生成 GLB")
    cleaned = inspect_ground_artifacts(destination)
    if cleaned["faces"] != report["faces"] - report["removable_faces"]:
        raise ValueError("清理后的三角面数量异常")
    return {
        "source": str(source),
        "output": str(destination),
        "original_faces": report["faces"],
        "remaining_faces": cleaned["faces"],
        "removed_faces": report["removable_faces"],
        "remaining_ground_anomaly": cleaned["ground_anomaly_detected"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = (
        remove_detached_ground(args.source, args.output)
        if args.output else inspect_ground_artifacts(args.source)
    )
    result.pop("candidate_faces", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
