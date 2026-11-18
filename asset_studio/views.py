import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


VIEW_NAMES = ("front", "right", "back", "left")
VIEW_AZIMUTHS = {"front": 0, "right": 90, "back": 180, "left": 270}
CANVAS_SIZE = 1024
SUBJECT_HEIGHT_RATIO = 0.80


def _normalize_view(source: Path, destination: Path) -> dict:
    with Image.open(source) as original:
        original.load()
        rgba = original.convert("RGBA")
        alpha = np.asarray(rgba.getchannel("A"))
        # 先将现有透明度复合到白底，最后保存 RGB，由 Pixal3D 官方抠图模型生成遮罩。
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")

    pixels = np.asarray(image)
    foreground = np.any(pixels < 225, axis=2)
    row_counts = np.count_nonzero(foreground, axis=1)
    col_counts = np.count_nonzero(foreground, axis=0)
    rows = np.flatnonzero(row_counts >= max(3, math.ceil(image.width * 0.008)))
    columns = np.flatnonzero(col_counts >= max(3, math.ceil(image.height * 0.008)))
    foreground_ratio = float(np.mean(foreground))
    if not len(rows) or not len(columns) or foreground_ratio > 0.65:
        raise ValueError(f"参考图背景或主体检测失败：{source.name}，前景比例 {foreground_ratio:.3f}")

    left, right = int(columns[0]), int(columns[-1]) + 1
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    subject_width, subject_height = right - left, bottom - top
    if subject_height < image.height * 0.35 or subject_width < image.width * 0.1:
        raise ValueError(f"参考图主体不完整：{source.name}")

    scale = min(
        CANVAS_SIZE * SUBJECT_HEIGHT_RATIO / subject_height,
        CANVAS_SIZE * 0.88 / subject_width,
    )
    subject = image.crop((left, top, right, bottom))
    width = max(1, round(subject_width * scale))
    height = max(1, round(subject_height * scale))
    subject = subject.resize((width, height), Image.Resampling.LANCZOS)
    output = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (255, 255, 255))
    output.paste(subject, ((CANVAS_SIZE - width) // 2, (CANVAS_SIZE - height) // 2))
    output.save(destination, format="PNG")
    with Image.open(destination) as check:
        check.verify()

    return {
        "source": str(source),
        "source_dimensions": [image.width, image.height],
        "source_alpha_range": [int(alpha.min()), int(alpha.max())],
        "source_foreground_ratio": round(foreground_ratio, 5),
        "source_subject_bbox": [left, top, right, bottom],
        "normalized_subject_dimensions": [width, height],
        "output_dimensions": [CANVAS_SIZE, CANVAS_SIZE],
        "output_mode": "RGB",
        "background_removal": "Pixal3D official rembg",
    }


def prepare_pixal_views(
    pixal_repo: Path,
    images: Path,
    destination: Path,
    view_names: tuple[str, ...] = VIEW_NAMES,
) -> Path:
    if not view_names or view_names[0] != "front" or len(view_names) != len(set(view_names)):
        raise ValueError("相机参考图必须以 front 开始且没有重复视角")
    if any(name not in VIEW_AZIMUTHS for name in view_names):
        raise ValueError("参考图包含未知视角")

    preset = pixal_repo / "assets" / "mv_images" / "example" / "transforms.json"
    template = json.loads(preset.read_text(encoding="utf-8"))
    if len(template["frames"]) != len(VIEW_NAMES):
        raise ValueError("Pixal3D 官方相机模板数量不符合要求")
    destination.mkdir(parents=True, exist_ok=True)
    source_frames = {
        name: template["frames"][index]
        for index, name in enumerate(VIEW_NAMES)
    }

    diagnostics = []
    frames = []
    for index, name in enumerate(view_names):
        source = images / f"{name}.png"
        if not source.is_file():
            raise FileNotFoundError(f"缺少 {name} 视角原画：{source}")
        frame = json.loads(json.dumps(source_frames[name]))
        filename = f"view{index:02d}_azim{VIEW_AZIMUTHS[name]:03d}.png"
        frame["file_path"] = filename
        frame["name"] = name
        diagnostics.append({"view": name, **_normalize_view(source, destination / filename)})
        frames.append(frame)

    heights = [item["normalized_subject_dimensions"][1] for item in diagnostics]
    if max(heights) - min(heights) > CANVAS_SIZE * 0.12:
        raise ValueError(f"参考图主体尺寸差异过大：{heights}")
    template["frames"] = frames
    template["camera_source"] = "Pixal3D official canonical turntable sample"
    template["camera_pose_verified"] = False
    manifest = destination / "transforms.json"
    manifest.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "preflight.json").write_text(json.dumps({
        "source": "Qwen generated images",
        "camera_pose_verified": False,
        "camera_azimuths_assumed": [VIEW_AZIMUTHS[name] for name in view_names],
        "views": diagnostics,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
