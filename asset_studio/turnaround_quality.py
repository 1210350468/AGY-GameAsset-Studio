from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


VIEW_NAMES = ("front", "right", "back", "left")


def inspect_turnaround(
    paths: dict[str, Path], *,
    origin: str,
) -> dict:
    if origin not in {"qimage_generated", "uploaded_four_view"}:
        raise ValueError("多视图来源必须明确")
    if set(paths) not in ({"front", "back"}, set(VIEW_NAMES)):
        raise ValueError("多视图必须包含正背双视图或标准四视图")

    captures = {}
    for view in VIEW_NAMES:
        if view not in paths:
            continue
        path = paths[view].resolve(strict=True)
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            if min(image.size) < 512:
                raise ValueError(f"{view} 视图清晰度不足：{image.size}")
            frame = np.asarray(image.resize((128, 128), Image.Resampling.BILINEAR), dtype=np.uint8)
        subject_mask = np.min(frame, axis=2) < 242
        population = float(subject_mask.mean())
        if not 0.035 <= population <= 0.72:
            raise ValueError(f"{view} 视图的主体或白底异常，主体面积比例 {population:.2%}")
        ys, xs = np.where(subject_mask)
        bounds = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        height = (bounds[3] - bounds[1] + 1) / 128
        if height < 0.45:
            raise ValueError(f"{view} 视图主体高度不足")
        colors = frame[subject_mask].astype(np.float64)
        captures[view] = {
            "file": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": list(image.size),
            "foreground_ratio": round(population, 5),
            "subject_bounds_128": bounds,
            "subject_height": round(height, 5),
            "mean_foreground_rgb": np.round(colors.mean(axis=0), 2).tolist(),
            "pixels": frame,
        }

    first = captures["front"]
    problems = []
    pair_metrics = []
    for name, candidate in captures.items():
        if name == "front":
            continue
        height_ratio = candidate["subject_height"] / first["subject_height"]
        area_ratio = candidate["foreground_ratio"] / first["foreground_ratio"]
        palette_distance = float(np.mean(np.abs(
            np.array(candidate["mean_foreground_rgb"]) -
            np.array(first["mean_foreground_rgb"]),
        )))
        pixel_delta = float(np.mean(np.abs(
            candidate["pixels"].astype(np.float32) - first["pixels"].astype(np.float32),
        ))) / 255.0
        metrics = {
            "view": name,
            "subject_height_ratio": round(height_ratio, 4),
            "foreground_area_ratio": round(area_ratio, 4),
            "mean_palette_distance": round(palette_distance, 3),
            "pixel_difference": round(pixel_delta, 5),
        }
        pair_metrics.append(metrics)
        if candidate["sha256"] == first["sha256"] or pixel_delta < 0.009:
            problems.append(f"{name} 与正面接近相同图像，缺少有效视角变化")
        if not 0.77 <= height_ratio <= 1.23:
            problems.append(f"{name} 与正面主体身高比例差异过大：{height_ratio:.2f}")
        minimum_area_ratio = 0.35 if name in {"right", "left"} else 0.55
        if not minimum_area_ratio <= area_ratio <= 1.9:
            problems.append(f"{name} 与正面主体面积差异过大：{area_ratio:.2f}")
        if palette_distance > 70:
            problems.append(f"{name} 与正面服装/主体配色差异过大")
    hashes = [item["sha256"] for item in captures.values()]
    if len(hashes) != len(set(hashes)):
        problems.append("多视图之间存在重复的参考原画")

    for capture in captures.values():
        capture.pop("pixels")
    return {
        "source": "真实 PNG 内容、主体几何占比、颜色与像素差异",
        "origin": origin,
        "camera_pose_verified": False,
        "semantic_identity_verified": False,
        "requires_visual_review": True,
        "camera_assumption": "Pixal3D 官方四方向、相同高度与距离的水平转台",
        "views": captures,
        "pair_metrics": pair_metrics,
        "preflight_passed": not problems,
        "issues": problems,
    }


def write_turnaround_quality(
    paths: dict[str, Path], destination: Path, *, origin: str,
) -> dict:
    result = inspect_turnaround(paths, origin=origin)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result["preflight_passed"]:
        raise ValueError("QImage/Pixal3D 多视图一致性检查失败：" + "；".join(result["issues"]))
    return result
