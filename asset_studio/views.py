import json
import shutil
from pathlib import Path

from PIL import Image


VIEW_NAMES = ("front", "right", "back", "left")


def prepare_pixal_views(pixal_repo: Path, images: Path, destination: Path) -> Path:
    preset = pixal_repo / "assets" / "mv_images" / "example" / "transforms.json"
    template = json.loads(preset.read_text(encoding="utf-8"))
    if len(template["frames"]) != len(VIEW_NAMES):
        raise ValueError("Pixal3D 标准相机数量与参考视角数量不一致")
    destination.mkdir(parents=True, exist_ok=True)
    for frame, name in zip(template["frames"], VIEW_NAMES, strict=True):
        original = images / f"{name}.png"
        if not original.is_file():
            raise FileNotFoundError(f"缺少 {name} 视角原画：{original}")
        with Image.open(original) as image:
            image.verify()
        filename = frame["file_path"]
        shutil.copy2(original, destination / filename)
        frame["name"] = name
    manifest = destination / "transforms.json"
    manifest.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return manifest
