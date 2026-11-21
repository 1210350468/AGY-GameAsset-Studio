from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import label


def inspect_candidate(path: Path, *, animated: bool) -> dict:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR), dtype=np.uint8)
        dimensions = list(image.size)
    mask = np.min(rgb, axis=2) < 242
    occupancy = float(mask.mean())
    labeled, count = label(mask)
    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0
    if count == 0 or sizes.max() == 0:
        raise ValueError(f"原画没有可识别的前景：{path}")
    main_mask = labeled == sizes.argmax()
    ys, xs = np.nonzero(main_mask)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    height_ratio = (bbox[3] - bbox[1] + 1) / 256
    width_ratio = (bbox[2] - bbox[0] + 1) / 256
    center_offset = abs((bbox[0] + bbox[2]) / 2 - 127.5) / 128
    corner = np.concatenate((
        rgb[:16, :16].reshape(-1, 3),
        rgb[:16, -16:].reshape(-1, 3),
        rgb[-16:, :16].reshape(-1, 3),
        rgb[-16:, -16:].reshape(-1, 3),
    ))
    background_brightness = float(corner.mean())
    border_activity = float(np.mean(np.concatenate((
        mask[:4].ravel(), mask[-4:].ravel(), mask[:, :4].ravel(), mask[:, -4:].ravel(),
    ))))
    problems = []
    if min(dimensions) < 512:
        problems.append("原画分辨率不足")
    if not 0.04 <= occupancy <= 0.70:
        problems.append("主体前景比例异常")
    if animated and height_ratio < 0.61:
        problems.append("角色或怪物没有足够的全身展示空间")
    if background_brightness < 228:
        problems.append("背景包含过多景物和阴影")
    if border_activity > 0.065:
        problems.append("主体靠近画面边缘，可能存在截断")
    if center_offset > 0.45:
        problems.append("主体明显偏离画面中心")
    score = (
        0.35 * max(0.0, 1 - abs(height_ratio - (0.80 if animated else 0.72)) * 1.7)
        + 0.20 * max(0, 1 - center_offset)
        + 0.20 * background_brightness / 255
        + 0.15 * max(0, 1 - border_activity * 5)
        + 0.10 * max(0, 1 - abs(occupancy - 0.23))
    )
    return {
        "file": str(path),
        "dimensions": dimensions,
        "subject_bbox_256": bbox,
        "foreground_ratio": round(occupancy, 5),
        "subject_height_ratio": round(height_ratio, 5),
        "subject_width_ratio": round(width_ratio, 5),
        "background_brightness": round(background_brightness, 3),
        "border_activity": round(border_activity, 5),
        "framing_score": round(float(score), 5),
        "preflight_passed": not problems,
        "issues": problems,
    }


def select_concept_candidate(
    candidates: list[Path], report_file: Path, *, animated: bool,
) -> Path:
    if not candidates:
        raise ValueError("QImage 没有生成原画")
    measurements = [inspect_candidate(path, animated=animated) for path in candidates]
    valid = [(item["framing_score"], index) for index, item in enumerate(measurements) if item["preflight_passed"]]
    selected = max(valid)[1] if valid else None
    result = {
        "selection_basis": "真实原画的完整主体、构图中心、白底和边缘裁切",
        "selected_candidate": selected + 1 if selected is not None else None,
        "visual_quality_verified": False,
        "candidates": measurements,
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if selected is None:
        raise ValueError("所有 QImage 候选的建模参考图检查均失败：" + "；".join(
            f"候选{index + 1}：{','.join(item['issues'])}" for index, item in enumerate(measurements)
        ))
    return candidates[selected]
