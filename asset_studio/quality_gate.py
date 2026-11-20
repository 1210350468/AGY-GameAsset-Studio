from __future__ import annotations

from pathlib import Path

from asset_studio.quality import inspect_model


MIN_LARGEST_COMPONENT_RATIO = 0.97
MAX_NON_MANIFOLD_EDGE_RATIO = 0.0035
MAX_BOUNDARY_EDGE_RATIO = 0.005
MAX_COMPONENT_LOSS_AFTER_BLENDER = 0.01
MIN_ASSEMBLY_COVERAGE = 0.94
MAX_ASSEMBLY_FRAGMENT_RATIO = 0.035
MAX_ASSEMBLY_NON_MANIFOLD_EDGE_RATIO = 0.01


def assess_game_mesh_report(
    quality: dict, *, baseline: dict | None = None, profile: str = "character",
) -> dict:
    quality = dict(quality)
    issues: list[str] = []
    assembled = profile in {"weapon", "equipment", "prop", "scene"}
    if not assembled and quality["largest_component_ratio"] < MIN_LARGEST_COMPONENT_RATIO:
        issues.append(
            f"最大连续网格比例 {quality['largest_component_ratio']:.2%}，要求至少 {MIN_LARGEST_COMPONENT_RATIO:.0%}"
        )
    if assembled:
        coverage = quality["component_coverage"]["top_32"]
        if coverage < MIN_ASSEMBLY_COVERAGE:
            issues.append(
                f"多部件资产前 32 个主要部件覆盖率 {coverage:.2%}，要求至少 {MIN_ASSEMBLY_COVERAGE:.0%}"
            )
        fragments = quality["fragment_faces_ratio"]
        if fragments > MAX_ASSEMBLY_FRAGMENT_RATIO:
            issues.append(
                f"多部件资产细碎浮空网格面积 {fragments:.2%}，超过 {MAX_ASSEMBLY_FRAGMENT_RATIO:.1%}"
            )
    edge_limit = MAX_ASSEMBLY_NON_MANIFOLD_EDGE_RATIO if assembled else MAX_NON_MANIFOLD_EDGE_RATIO
    if quality["non_manifold_edge_ratio"] > edge_limit:
        issues.append(
            f"非流形边比例 {quality['non_manifold_edge_ratio']:.3%}，要求不超过 {edge_limit:.2%}"
        )
    if quality["boundary_edge_ratio"] > MAX_BOUNDARY_EDGE_RATIO:
        issues.append(
            f"开放边界比例 {quality['boundary_edge_ratio']:.3%}，要求不超过 {MAX_BOUNDARY_EDGE_RATIO:.2%}"
        )
    if any(not metric["winding_consistent"] for metric in quality["mesh_metrics"]):
        issues.append("网格面朝向不一致")
    if quality["images"] == 0:
        issues.append("模型缺少材质贴图")
    if baseline is not None:
        reduction = baseline["largest_component_ratio"] - quality["largest_component_ratio"]
        if reduction > MAX_COMPONENT_LOSS_AFTER_BLENDER:
            issues.append(f"Blender 处理损失 {reduction:.2%} 的连续网格比例")
        if quality["non_manifold_edges"] > baseline["non_manifold_edges"] * 1.1 + 100:
            issues.append("Blender 处理明显增加了非流形边")
        if quality["boundary_edges"] > baseline["boundary_edges"] * 2 + 100:
            issues.append("Blender 处理明显增加了开放边界")

    quality["geometry_profile"] = profile
    quality["game_ready"] = len(issues) == 0
    quality["game_readiness_reasons"] = issues
    return quality


def inspect_game_mesh_quality(
    model: Path, *, baseline: dict | None = None, profile: str = "character",
) -> dict:
    return assess_game_mesh_report(inspect_model(model), baseline=baseline, profile=profile)


def require_ready_geometry(quality: dict) -> None:
    if not quality["game_ready"]:
        raise ValueError(f"三维资产质量验收失败：{'；'.join(quality['game_readiness_reasons'])}")


def require_game_mesh_quality(model: Path, *, baseline: dict | None = None) -> dict:
    quality = inspect_game_mesh_quality(model, baseline=baseline)
    require_ready_geometry(quality)
    return quality
