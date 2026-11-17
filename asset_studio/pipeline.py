import json
import os
import queue
import shutil
import subprocess
import threading
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any

import trimesh
from pygltflib import GLTF2

from asset_studio.comfy import generate_image
from asset_studio.settings import Settings
from asset_studio.gpu import require_gpu_headroom
from asset_studio.store import Store, timestamp


class AssetPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.prepare_directories()
        self.store = Store(settings.data_root / "jobs.sqlite3")
        self.store.recover_interrupted()
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True, name="asset-studio-gpu-worker")
        self.started = False

    def start(self) -> None:
        if self.started:
            raise RuntimeError("Worker already started")
        self.thread = threading.Thread(target=self._worker, daemon=True, name="asset-studio-gpu-worker")
        self.thread.start()
        self.started = True
        for job in reversed(self.store.list(limit=10000)):
            if job["status"] == "queued":
                self.jobs.put(job["id"])

    def close(self) -> None:
        if self.started:
            self.jobs.put(None)
            self.thread.join(timeout=2)
            if not self.thread.is_alive():
                self.started = False

    def create(self, *, title: str, kind: str, mode: str, params: dict[str, Any], input_bytes: bytes | None) -> str:
        job_id = uuid.uuid4().hex
        job_dir = self.settings.jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        if input_bytes is not None:
            suffix = ".glb" if mode == "import" else ".png"
            (job_dir / f"input{suffix}").write_bytes(input_bytes)
        self.store.create(job_id, title, kind, mode, params)
        self.jobs.put(job_id)
        return job_id

    def readiness(self) -> dict[str, Any]:
        settings = self.settings
        comfy_path = settings.sources / "ComfyUI-v0.29.2" / "main.py"
        completed = settings.data_root / "installed"
        return {
            "anime": {"model": settings.checkpoint, "installed": settings.image_checkpoint.is_file() and comfy_path.is_file() and (completed / "anime").is_file()},
            "pixal3d": {"installed": settings.pixal_python.is_file() and (settings.pixal_repo / "inference.py").is_file() and (settings.pixal_model_path / "pipeline.json").is_file() and (completed / "pixal3d").is_file()},
            "partcrafter": {"installed": settings.part_python.is_file() and (settings.part_repo / "scripts" / "inference_partcrafter.py").is_file() and (completed / "partcrafter").is_file()},
            "skintokens": {"installed": settings.rig_python.is_file() and (settings.rig_repo / "demo.py").is_file() and (completed / "skintokens").is_file()},
            "blender": {"installed": settings.blender_binary() is not None},
        }

    def _worker(self) -> None:
        while True:
            job_id = self.jobs.get()
            if job_id is None:
                self.jobs.task_done()
                return
            try:
                self._execute(job_id)
            except Exception as error:
                self.store.update(job_id, status="failed", stage="failed", progress=0, error=str(error))
                with (self.settings.jobs_root / job_id / "process.log").open("a", encoding="utf-8") as log:
                    log.write(traceback.format_exc())
            finally:
                self.jobs.task_done()

    def _stage(self, job_id: str, stage: str, progress: float) -> None:
        self.store.update(job_id, status="running", stage=stage, progress=progress)

    def _command(self, args: list[str], *, cwd: Path, log, env: dict[str, str] | None = None) -> None:
        command_environment = os.environ.copy()
        command_environment["TMPDIR"] = str(self.settings.data_root / "scratch")
        command_environment["TMP"] = command_environment["TMPDIR"]
        command_environment["TEMP"] = command_environment["TMPDIR"]
        (self.settings.data_root / "scratch").mkdir(exist_ok=True)
        if env:
            command_environment.update(env)
        log.write("COMMAND: " + json.dumps(args, ensure_ascii=False) + "\n")
        log.flush()
        subprocess.run(
            args, cwd=cwd, env=command_environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, timeout=self.settings.timeout_seconds, check=True,
        )

    def _execute(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job_dir = self.settings.jobs_root / job_id
        params = job["params"]
        settings = self.settings
        with (job_dir / "process.log").open("a", encoding="utf-8") as log:
            log.write(f"[{timestamp()}] {job['title']} : {job['mode']}\n")
            log.flush()

            if job["mode"] == "import":
                self._stage(job_id, "导入 GLB", 0.15)
                generated = job_dir / "input.glb"
            else:
                require_gpu_headroom(settings)
                concept = job_dir / "input.png"
                if not concept.is_file():
                    self._stage(job_id, "生成二次元原画", 0.12)
                    if not settings.image_checkpoint.is_file():
                        raise FileNotFoundError(f"图像模型权重缺失：{settings.image_checkpoint}")
                    generate_image(
                        base_url=settings.comfy_url, checkpoint=settings.checkpoint,
                        prompt=params["prompt"], destination=concept, seed=params["seed"],
                        steps=params["image_steps"], timeout_seconds=settings.timeout_seconds, log=log,
                    )

                if job["mode"] == "whole":
                    self._stage(job_id, "Pixal3D 重建与材质生成", 0.35)
                    generated = job_dir / "generated.glb"
                    args = [
                        str(settings.pixal_python), "inference.py", "--image", str(concept),
                        "--output", str(generated), "--seed", str(params["seed"]),
                        "--model_path", str(settings.pixal_model_path),
                    ]
                    if settings.pixal_low_vram:
                        args.extend(["--low_vram", "--resolution", "1024"])
                    else:
                        args.extend(["--resolution", "1536"])
                    self._command(args, cwd=settings.pixal_repo, log=log, env={"ATTN_BACKEND": "sdpa"})
                elif job["mode"] == "parts":
                    self._stage(job_id, "PartCrafter 分部件建模", 0.35)
                    output_root = job_dir / "partcrafter"
                    args = [
                        str(settings.part_python), "scripts/inference_partcrafter.py",
                        "--image_path", str(concept), "--output_dir", str(output_root),
                        "--tag", job_id, "--num_parts", str(params["num_parts"]),
                        "--seed", str(params["seed"]), "--rmbg",
                    ]
                    self._command(
                        args, cwd=settings.part_repo, log=log,
                        env={"PYTHONPATH": str(settings.part_repo) + os.pathsep + os.environ.get("PYTHONPATH", "")},
                    )
                    generated = output_root / job_id / "object.glb"
                else:
                    raise RuntimeError(f"Unsupported mode: {job['mode']}")

                if params["rig"]:
                    require_gpu_headroom(settings)
                    self._stage(job_id, "SkinTokens 骨骼与蒙皮", 0.64)
                    rigged = job_dir / "rigged.glb"
                    self._command(
                        [str(settings.rig_python), "demo.py", "--input", str(generated),
                         "--output", str(rigged), "--use_transfer"],
                        cwd=settings.rig_repo, log=log,
                    )
                    generated = rigged

            if not generated.is_file() or generated.stat().st_size == 0:
                raise FileNotFoundError(f"3D 模型没有生成：{generated}")

            self._stage(job_id, "Blender 优化与统一导出", 0.82)
            final_model = job_dir / "model.glb"
            blender = settings.blender_binary()
            if blender is None:
                raise FileNotFoundError("Blender 未安装，无法完成游戏模型加工")
            self._command(
                [blender, "--background", "--python", str(settings.root / "blender" / "prepare_asset.py"),
                 "--", "--input", str(generated), "--output", str(final_model),
                 "--target-faces", str(params["target_faces"])],
                cwd=job_dir, log=log,
            )

            self._stage(job_id, "检查模型并打包 Godot 资源", 0.93)
            self._package(job, job_dir, final_model)
            self.store.update(job_id, status="completed", stage="completed", progress=1.0)

    def _package(self, job: dict[str, Any], job_dir: Path, final_model: Path) -> None:
        scene = trimesh.load(final_model, force="scene")
        geometries = [geometry for geometry in scene.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not geometries or sum(len(mesh.faces) for mesh in geometries) == 0:
            raise ValueError("GLB 无有效三角面，模型验收失败")
        gltf = GLTF2().load(str(final_model))
        has_skeleton = bool(gltf.skins)
        if job["params"].get("rig") and not has_skeleton:
            raise ValueError("自动骨骼任务导出的 GLB 缺少 skin，模型验收失败")
        face_count = sum(len(mesh.faces) for mesh in geometries)
        bounds = scene.bounds.tolist()
        quality = {
            "geometry_count": len(geometries),
            "faces": face_count,
            "bounds": bounds,
            "skinned": has_skeleton,
            "watertight_meshes": sum(bool(mesh.is_watertight) for mesh in geometries),
            "source": "actual GLB geometry inspection",
        }
        (job_dir / "quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = {
            "asset_id": job["id"], "title": job["title"], "type": job["kind"],
            "mode": job["mode"], "created_at": job["created_at"],
            "model": "model.glb", "engine": "Godot 4", "quality": quality,
            "rig_generated": has_skeleton,
            "animations_included": bool(gltf.animations),
        }
        (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        included = ["model.glb", "quality.json", "manifest.json"]
        if (job_dir / "input.png").exists():
            included.append("input.png")
        for part in sorted((job_dir / "partcrafter" / job["id"]).glob("part_*.glb")):
            included.append(str(part.relative_to(job_dir)))
        bundle_path = job_dir / "godot_asset.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
            for relative in included:
                archive.write(job_dir / relative, arcname=relative)

