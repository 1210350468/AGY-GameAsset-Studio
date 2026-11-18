import argparse
import json
import os
import subprocess
from pathlib import Path

from asset_studio.gpu import choose_3d_gpu
from asset_studio.quality import inspect_model
from asset_studio.settings import Settings
from asset_studio.views import prepare_pixal_views


parser = argparse.ArgumentParser(description="运行官方 Pixal3D 单视角、前后视角、四视角真实重建对照")
parser.add_argument("--data-root", type=Path, required=True)
parser.add_argument("--source-views", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--prepare-only", action="store_true")
parser.add_argument("--modes", nargs="+", choices=["single", "front-back", "four"],
                    default=["single", "front-back", "four"])
parser.add_argument("--seed", type=int, default=20261118)
args = parser.parse_args()

os.environ["ASSET_STUDIO_DATA_ROOT"] = str(args.data_root.resolve(strict=True))
settings = Settings.from_environment()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
views = {
    "single": ("front",),
    "front-back": ("front", "back"),
    "four": ("front", "right", "back", "left"),
}

for mode in args.modes:
    folder = output / mode
    view_dir = folder / "views"
    manifest = prepare_pixal_views(settings.pixal_repo, args.source_views, view_dir, views[mode])
    summary = json.loads((view_dir / "preflight.json").read_text(encoding="utf-8"))
    print(json.dumps({"mode": mode, "manifest": str(manifest), "input": summary}, ensure_ascii=False), flush=True)
    if args.prepare_only:
        continue

    model = folder / "generated.glb"
    if model.is_file():
        quality = inspect_model(model)
        print(json.dumps({"mode": mode, "existing_model_quality": quality}, ensure_ascii=False), flush=True)
        continue

    gpu_index = choose_3d_gpu(settings, low_vram_pixal=True)
    command = [str(settings.pixal_python), "inference.py" if mode == "single" else "inference_mv.py"]
    command.extend(["--image", str(view_dir / "view00_azim000.png")]
                   if mode == "single" else ["--views_dir", str(view_dir)])
    command.extend([
        "--output", str(model), "--seed", str(args.seed),
        "--model_path", str(settings.pixal_model_path),
        "--low_vram", "--resolution", "1024",
    ])
    if mode != "single":
        command.extend(["--config_file", "pipeline_mv_cached_birefnet.json"])

    environment = os.environ.copy()
    environment.update({
        "ATTN_BACKEND": "sdpa", "CUDA_VISIBLE_DEVICES": str(gpu_index),
        "HF_HOME": str(settings.data_root / "cache" / "huggingface"),
        "TORCH_HOME": str(settings.data_root / "cache" / "torch"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TMPDIR": str(settings.data_root / "scratch"),
        "PYTHONUNBUFFERED": "1",
    })
    settings_root = settings.pixal_repo
    print(json.dumps({"mode": mode, "gpu": gpu_index, "command": command}, ensure_ascii=False), flush=True)
    with (folder / "process.log").open("w", encoding="utf-8") as logfile:
        subprocess.run(command, cwd=settings_root, env=environment,
                       stdout=logfile, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, check=True, timeout=settings.timeout_seconds)
    quality = inspect_model(model)
    (folder / "raw_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": mode, "quality": quality}, ensure_ascii=False), flush=True)
