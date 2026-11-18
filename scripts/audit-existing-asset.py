import argparse
import json
import os
import subprocess
from pathlib import Path

from asset_studio.appearance import inspect_silhouette
from asset_studio.settings import Settings
from asset_studio.store import Store


parser = argparse.ArgumentParser(description="对已有真实 GLB 重新执行外观轮廓验收")
parser.add_argument("--job", required=True)
parser.add_argument("--reject", action="store_true")
args = parser.parse_args()

settings = Settings.from_environment()
job = Store(settings.data_root / "jobs.sqlite3").get(args.job)
if job is None or job["status"] not in {"completed", "review_required", "rejected"}:
    raise ValueError("只能复核已经生成完成的真实资产")
directory = settings.jobs_root / args.job
model = directory / "model.glb"
reference = directory / "input.png"
if not model.is_file() or not reference.is_file():
    raise FileNotFoundError("缺少原始参考图或完整模型")

blender = settings.blender_binary()
if blender is None:
    raise FileNotFoundError("Blender 未安装")
environment = os.environ.copy()
environment["CUDA_VISIBLE_DEVICES"] = ""
subprocess.run(
    [blender, "--background", "--python-exit-code", "1", "--python",
     str(settings.root / "blender" / "render_silhouettes.py"), "--",
     "--input", str(model), "--output", str(directory / "silhouettes")],
    env=environment, stdin=subprocess.DEVNULL, check=True, timeout=360,
)
report = inspect_silhouette(reference, directory / "silhouettes")
(directory / "appearance_quality.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
)
status = "rejected" if args.reject else "review_required"
Store(settings.data_root / "jobs.sqlite3").update(
    args.job, status=status,
    stage="外观不符合要求" if args.reject else "等待检查角色造型与材质", progress=1.0,
)
print(json.dumps({"job_id": args.job, "status": status, "appearance": report}, ensure_ascii=False))
