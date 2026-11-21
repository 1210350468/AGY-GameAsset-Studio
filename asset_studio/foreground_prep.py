from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes, gaussian_filter, label


def prepare_clean_foreground(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if source == destination:
        raise ValueError("去除背景必须保留原始图片")
    with Image.open(source) as opened:
        original = opened.convert("RGBA")
        rgb = np.asarray(original.convert("RGB"), dtype=np.uint8)
        old_alpha = np.asarray(original.getchannel("A"), dtype=np.uint8)

    height, width = rgb.shape[:2]
    if min(height, width) < 256:
        raise ValueError("原画分辨率不足")
    corners = np.concatenate((
        rgb[:height // 18, :width // 18].reshape(-1, 3),
        rgb[:height // 18, -width // 18:].reshape(-1, 3),
        rgb[-height // 18:, :width // 18].reshape(-1, 3),
        rgb[-height // 18:, -width // 18:].reshape(-1, 3),
    ))
    background = np.median(corners, axis=0)
    if np.min(background) < 230 or np.max(background) - np.min(background) > 18:
        raise ValueError("自动清理地面阴影要求浅色、颜色均匀的摄影棚背景")

    brightest = rgb.max(axis=2).astype(np.int16)
    darkest = rgb.min(axis=2).astype(np.int16)
    saturation = brightest - darkest
    raw_subject = (darkest < 231) | (saturation > 24)
    raw_subject &= old_alpha >= 64
    ys, xs = np.nonzero(raw_subject)
    if len(xs) < height * width * 0.02:
        raise ValueError("图片前景不足，无法生成可靠的透明遮罩")

    top, bottom = int(ys.min()), int(ys.max())
    if bottom - top < height * 0.35:
        raise ValueError("人物或怪物主体高度不足")
    lower_start = top + int((bottom - top) * 0.78)
    mask = raw_subject.copy()
    lower = np.arange(height)[:, None] >= lower_start
    neutral_light_shadow = (darkest >= 188) & (saturation <= 23)
    mask[lower & neutral_light_shadow] = False

    clusters, count = label(mask, structure=np.ones((3, 3), dtype=np.uint8))
    sizes = np.bincount(clusters.ravel())
    sizes[0] = 0
    largest = sizes.max()
    if largest < height * width * 0.015:
        raise ValueError("主体被分成过多独立区域，无法可靠清除背景")
    keep = np.flatnonzero(sizes >= max(64, largest * 0.012))
    foreground = np.isin(clusters, keep)
    foreground = binary_fill_holes(foreground)
    preserved_upper = np.count_nonzero(foreground[:lower_start])
    original_upper = np.count_nonzero(raw_subject[:lower_start])
    if preserved_upper / original_upper < 0.90:
        raise ValueError("遮罩丢失了重要的主体上半部分")
    if foreground.sum() > height * width * 0.65:
        raise ValueError("前景遮罩包含大量背景")

    alpha = (np.clip(gaussian_filter(foreground.astype(np.float32), sigma=0.8), 0, 1) * 255).astype(np.uint8)
    alpha = np.minimum(alpha, old_alpha)
    output = np.dstack((rgb, alpha))
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(output).save(destination)
    with Image.open(destination) as check:
        check.verify()
    result = {
        "source": str(source),
        "output": str(destination),
        "image_width": width,
        "image_height": height,
        "foreground_ratio_before": round(float(raw_subject.mean()), 5),
        "foreground_ratio_after": round(float(foreground.mean()), 5),
        "lower_subject_pixels_before": int(raw_subject[lower_start:].sum()),
        "lower_subject_pixels_after": int(foreground[lower_start:].sum()),
        "source_background_rgb": background.astype(int).tolist(),
        "kept_components": int(len(keep)),
        "transparent_pixel_ratio": round(float(np.mean(alpha < 128)), 5),
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_clean_foreground(args.source, args.destination), ensure_ascii=False, indent=2))
