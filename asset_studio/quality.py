import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh
from pygltflib import GLTF2
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


@lru_cache(maxsize=256)
def _inspect_cached(filename: str, file_size: int, modified_ns: int) -> dict:
    model = Path(filename)
    scene = trimesh.load(model, force="scene")
    geometries = [geometry for geometry in scene.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
    if not geometries:
        raise ValueError("GLB 缺少实际三角网格")

    mesh_metrics = []
    for source in geometries:
        mesh = source.copy()
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        adjacency = mesh.face_adjacency
        graph = coo_matrix(
            (np.ones(len(adjacency), dtype=np.int8), (adjacency[:, 0], adjacency[:, 1])),
            shape=(len(mesh.faces), len(mesh.faces)),
        ).tocsr()
        components, labels = connected_components(graph, directed=False)
        component_sizes = np.bincount(labels)
        edge_counts = np.bincount(mesh.edges_unique_inverse)
        boundary_edges = int(np.count_nonzero(edge_counts == 1))
        irregular_edges = int(np.count_nonzero(edge_counts > 2))
        mesh_metrics.append({
            "faces": int(len(mesh.faces)),
            "vertices": int(len(mesh.vertices)),
            "components": int(components),
            "largest_component_faces": int(component_sizes.max()),
            "boundary_edges": boundary_edges,
            "total_edges": int(len(edge_counts)),
            "non_manifold_edges": irregular_edges,
            "watertight": bool(mesh.is_watertight),
            "winding_consistent": bool(mesh.is_winding_consistent),
        })

    gltf = GLTF2().load(filename)
    faces = sum(mesh["faces"] for mesh in mesh_metrics)
    boundary_edges = sum(mesh["boundary_edges"] for mesh in mesh_metrics)
    total_edges = sum(mesh["total_edges"] for mesh in mesh_metrics)
    non_manifold_edges = sum(mesh["non_manifold_edges"] for mesh in mesh_metrics)
    largest_component = max(mesh["largest_component_faces"] for mesh in mesh_metrics)
    boundary_ratio = boundary_edges / total_edges
    irregular_ratio = non_manifold_edges / total_edges
    largest_ratio = largest_component / faces
    issues = []
    if boundary_ratio > 0.025:
        issues.append("模型存在较多开放边界，可能出现可见缺面")
    if largest_ratio < 0.3:
        issues.append("网格连续部分占比较低，可能存在破碎部件")
    if irregular_ratio > 0.01:
        issues.append("网格存在较多非流形连接，需要检查表面")
    if any(not mesh["winding_consistent"] for mesh in mesh_metrics):
        issues.append("部分面的朝向不一致，需要检查模型法线")
    if len(gltf.images) == 0:
        issues.append("模型缺少贴图，材质颜色需要检查")
    return {
        "source": "真实 GLB 网格检查，按三维坐标合并 UV 接缝顶点后统计",
        "faces": faces,
        "geometry_count": len(mesh_metrics),
        "components": sum(mesh["components"] for mesh in mesh_metrics),
        "largest_component_ratio": round(largest_ratio, 5),
        "boundary_edges": boundary_edges,
        "boundary_edge_ratio": round(boundary_ratio, 5),
        "non_manifold_edges": non_manifold_edges,
        "non_manifold_edge_ratio": round(irregular_ratio, 5),
        "watertight_meshes": sum(mesh["watertight"] for mesh in mesh_metrics),
        "materials": len(gltf.materials),
        "textures": len(gltf.textures),
        "images": len(gltf.images),
        "skinned": bool(gltf.skins),
        "joints": sum(len(skin.joints) for skin in gltf.skins),
        "mesh_metrics": mesh_metrics,
        "review_required": bool(issues),
        "review_reasons": issues,
    }


def inspect_model(model: Path) -> dict:
    path = model.resolve(strict=True)
    info = path.stat()
    return json.loads(json.dumps(_inspect_cached(str(path), info.st_size, info.st_mtime_ns)))
