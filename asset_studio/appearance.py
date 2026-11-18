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
