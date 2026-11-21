from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


SILHOUETTE_IOU_MINIMUM = 0.62
CANVAS_SIZE = 256
SUBJECT_HEIGHT = 220


def _main_subject(mask: np.ndarray) -> np.ndarray:
    labeled, count = ndimage.label(mask)
    if count == 0:
        raise ValueError("原画或模型投影缺少可识别的主体")
    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0
    subject = labeled == sizes.argmax()
    return ndimage.binary_fill_holes(subject)


def _reference_mask(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    foreground = np.min(rgb, axis=2) < 225
    if np.mean(foreground) >= 0.70:
        raise ValueError("原画背景无法可靠分离，请使用干净的浅色背景参考图")
    return _main_subject(foreground)


def _rendered_mask(image: Image.Image) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    if np.mean(alpha > 16) >= 0.90:
        raise ValueError("Blender 渲染未输出透明背景，无法执行轮廓比较")
    return _main_subject(alpha > 16)


def _normalize_subject(mask: np.ndarray) -> np.ndarray:
    y, x = np.nonzero(mask)
    if len(x) == 0:
        raise ValueError("主体轮廓为空")
    left, right = int(x.min()), int(x.max()) + 1
    top, bottom = int(y.min()), int(y.max()) + 1
    width, height = right - left, bottom - top
    scale = min(SUBJECT_HEIGHT / height, (CANVAS_SIZE - 12) / width)
    target_width = max(1, round(width * scale))
    target_height = max(1, round(height * scale))
    cropped = Image.fromarray(mask[top:bottom, left:right].astype(np.uint8) * 255)
    scaled = np.asarray(cropped.resize((target_width, target_height), Image.Resampling.NEAREST)) > 127
    result = np.zeros((CANVAS_SIZE, CANVAS_SIZE), dtype=bool)
    offset_x = (CANVAS_SIZE - target_width) // 2
    offset_y = (CANVAS_SIZE - target_height) // 2
    result[offset_y:offset_y + target_height, offset_x:offset_x + target_width] = scaled
    return result


def inspect_silhouette(reference: Path, renders: Path) -> dict:
    with Image.open(reference) as image:
        reference_mask = _normalize_subject(_reference_mask(image))
    results = []
    for azimuth in range(0, 360, 45):
        path = renders / f"silhouette_{azimuth:03d}.png"
        with Image.open(path) as image:
            rendered_mask = _normalize_subject(_rendered_mask(image))
        intersection = np.count_nonzero(reference_mask & rendered_mask)
        union = np.count_nonzero(reference_mask | rendered_mask)
        if union == 0:
            raise ValueError(f"投影轮廓面积无效：{path}")
        results.append({"azimuth": azimuth, "silhouette_iou": round(float(intersection / union), 5)})
    best = max(results, key=lambda item: item["silhouette_iou"])
    score = best["silhouette_iou"]
    return {
        "source": "原画主体与真实 GLB 正交投影的八方向轮廓交并比",
        "silhouette_iou": score,
        "best_azimuth": best["azimuth"],
        "views": results,
        "silhouette_passed": bool(score >= SILHOUETTE_IOU_MINIMUM),
        "silhouette_threshold": SILHOUETTE_IOU_MINIMUM,
        "visual_review_required": True,
        "review_reasons": ([f"原画轮廓一致性 {score:.1%} 低于 {SILHOUETTE_IOU_MINIMUM:.0%} 验收要求"]
                           if score < SILHOUETTE_IOU_MINIMUM else ["轮廓已检查，盔甲、面部、材质与服饰细节仍需审核"]),
    }


def inspect_multiview_silhouettes(
    references: Path,
    renders: Path,
    view_names: tuple[str, ...] = ("front", "right", "back", "left"),
) -> dict:
    azimuths = {"front": 0, "right": 90, "back": 180, "left": 270}
    if not view_names or any(name not in azimuths for name in view_names):
        raise ValueError("多视图轮廓核对要求标准转台参考角度")
    masks = {}
    for name in view_names:
        with Image.open(references / f"{name}.png") as image:
            masks[name] = _normalize_subject(_reference_mask(image))
    projections = {}
    for azimuth in range(0, 360, 45):
        with Image.open(renders / f"silhouette_{azimuth:03d}.png") as image:
            projections[azimuth] = _normalize_subject(_rendered_mask(image))

    candidates = []
    for offset in range(0, 360, 45):
        for direction in (1, -1):
            measured = []
            for name in view_names:
                angle = (offset + direction * azimuths[name]) % 360
                original = masks[name]
                projected = projections[angle]
                intersection = int(np.count_nonzero(original & projected))
                union = int(np.count_nonzero(original | projected))
                if union == 0:
                    raise ValueError("模型多视图轮廓比较存在空的投影")
                measured.append({
                    "view": name,
                    "render_azimuth": angle,
                    "silhouette_iou": round(intersection / union, 5),
                })
            average = sum(row["silhouette_iou"] for row in measured) / len(measured)
            candidates.append((average, offset, direction, measured))
    average, offset, direction, views = max(candidates, key=lambda item: item[0])
    minimum = min(view["silhouette_iou"] for view in views)
    passed = average >= 0.63 and minimum >= 0.46
    issues = []
    if average < 0.63:
        issues.append(f"四个角度的平均轮廓交并比 {average:.1%} 低于 63%")
    if minimum < 0.46:
        issues.append(f"最弱视角轮廓交并比 {minimum:.1%} 低于 46%")
    return {
        "source": "真实 Pixal3D GLB 的八方向 Blender 投影与原始四视图逐项比较",
        "comparison_rule": "所有视角使用统一的旋转偏移和固定旋转方向",
        "azimuth_offset": offset,
        "azimuth_direction": direction,
        "mean_silhouette_iou": round(average, 5),
        "min_silhouette_iou": round(minimum, 5),
        "views": views,
        "multiview_passed": passed,
        "visual_review_required": True,
        "issues": issues,
    }
