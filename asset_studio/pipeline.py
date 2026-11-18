import json
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any

import trimesh
from pygltflib import GLTF2

from asset_studio.image_models import render_concept, render_reference_views
from asset_studio.settings import Settings
from asset_studio.gpu import GpuCapacityBusy, choose_3d_gpu
from asset_studio.nextgen import require_gpu_headroom as require_nextgen_gpu_headroom
from asset_studio.views import prepare_pixal_views
from asset_studio.quality import inspect_model
from asset_studio.quality_gate import inspect_game_mesh_quality, require_ready_geometry
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

    def create(
        self, *, title: str, kind: str, mode: str,
        params: dict[str, Any], input_bytes: bytes | None,
        reference_image_bytes: bytes | None = None,
        reference_views: dict[str, bytes] | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        job_dir = self.settings.jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        if input_bytes is not None:
            suffix = ".glb" if mode == "import" else ".png"
            (job_dir / f"input{suffix}").write_bytes(input_bytes)
        if reference_image_bytes is not None:
            (job_dir / "input.png").write_bytes(reference_image_bytes)
        if reference_views is not None:
            views_dir = job_dir / "views"
            views_dir.mkdir()
            for name, image_bytes in reference_views.items():
                if name not in {"front", "right", "back", "left"}:
                    raise ValueError("参考图视角无效")
                (views_dir / f"{name}.png").write_bytes(image_bytes)
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
            "godot": {"installed": settings.godot_binary() is not None},
        }

    def _worker(self) -> None:
        while True:
            job_id = self.jobs.get()
            if job_id is None:
                self.jobs.task_done()
                return
            try:
                self._execute(job_id)
            except GpuCapacityBusy as error:
                current = self.store.get(job_id)
                self.store.update(job_id, status="queued", stage=str(error), progress=current["progress"])
                self.jobs.put(job_id)
                time.sleep(30)
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
        command_environment["TORCH_HOME"] = str(self.settings.data_root / "cache" / "torch")
        command_environment["HF_HOME"] = str(self.settings.data_root / "cache" / "huggingface")
        command_environment["PYTHONUNBUFFERED"] = "1"
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
                concept = job_dir / "input.png"
                if not concept.is_file():
                    model = params.get("image_model", "wai")
                    if model in {"qwen", "anima"}:
                        gpu_file = settings.data_root / f"nextgen-{model}-gpu"
                        gpu_index = int(gpu_file.read_text(encoding="utf-8").strip())
                        try:
                            require_nextgen_gpu_headroom(model, gpu_index)
                        except RuntimeError as error:
                            raise GpuCapacityBusy(str(error)) from error
                    elif model == "wai":
                        from asset_studio.gpu import memory_headroom
                        memory = memory_headroom(settings)
                        if not memory["ready"]:
                            raise GpuCapacityBusy(f"WAI 当前 GPU 空闲显存 {memory['free_mib']} MiB，要求 {memory['required_mib']} MiB")
                    self._stage(job_id, f"{model} 生成原画", 0.12)
                    render_concept(
                        settings=settings, model=model, prompt=params["prompt"], kind=job["kind"],
                        seed=params["seed"], steps=params["image_steps"],
                        candidates=params.get("image_count", 1), destination=concept, log=log,
                    )

                use_multiview = bool(params.get("multi_views"))
                if use_multiview and not (job_dir / "pixal_views" / "transforms.json").is_file():
                    views = job_dir / "views"
                    if not all((views / f"{name}.png").is_file() for name in ("front", "right", "back", "left")):
                        gpu_index = int((settings.data_root / "nextgen-qwen-gpu").read_text(encoding="utf-8").strip())
                        try:
                            require_nextgen_gpu_headroom("qwen", gpu_index)
                        except RuntimeError as error:
                            raise GpuCapacityBusy(str(error)) from error
                        self._stage(job_id, "Qwen 生成四视角参考", 0.27)
                        views.mkdir(exist_ok=True)
                        render_reference_views(settings, concept, params["prompt"], views, params["seed"], log)
                    prepare_pixal_views(settings.pixal_repo, views, job_dir / "pixal_views")

                if job["mode"] == "whole":
                    generated = job_dir / "generated.glb"
                    if not generated.is_file():
                        low_vram = params.get("pixal_low_vram", settings.pixal_low_vram)
                        gpu_index = choose_3d_gpu(settings, low_vram_pixal=low_vram)
                        self._stage(job_id, "Pixal3D 多视角重建" if use_multiview else "Pixal3D 重建与材质生成", 0.35)
                        args = [
                            str(settings.pixal_python), "inference_mv.py" if use_multiview else "inference.py",
                        ]
                        args.extend(["--views_dir", str(job_dir / "pixal_views")] if use_multiview else ["--image", str(concept)])
                        args.extend([
                            "--output", str(generated), "--seed", str(params["seed"]),
                            "--model_path", str(settings.pixal_model_path),
                        ])
                        if use_multiview:
                            args.extend(["--config_file", "pipeline_mv_cached_birefnet.json"])
                        if low_vram:
                            args.extend(["--low_vram", "--resolution", "1024"])
                        else:
                            args.extend(["--resolution", "1536"])
                        self._command(args, cwd=settings.pixal_repo, log=log, env={
                            "ATTN_BACKEND": "sdpa", "CUDA_VISIBLE_DEVICES": str(gpu_index),
                            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                        })
                elif job["mode"] == "parts":
                    gpu_index = choose_3d_gpu(settings)
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
                        env={"PYTHONPATH": str(settings.part_repo) + os.pathsep + os.environ.get("PYTHONPATH", ""), "CUDA_VISIBLE_DEVICES": str(gpu_index)},
                    )
                    generated = output_root / job_id / "object.glb"
                else:
                    raise RuntimeError(f"Unsupported mode: {job['mode']}")

                if params["rig"]:
                    gpu_index = choose_3d_gpu(settings)
                    self._stage(job_id, "SkinTokens 骨骼与蒙皮", 0.64)
                    rigged = job_dir / "rigged.glb"
                    self._command(
                        [str(settings.rig_python), "demo.py", "--input", str(generated),
                         "--output", str(rigged), "--use_transfer"],
                        cwd=settings.rig_repo, log=log, env={"CUDA_VISIBLE_DEVICES": str(gpu_index)},
                    )
                    generated = rigged

            if not generated.is_file() or generated.stat().st_size == 0:
                raise FileNotFoundError(f"3D 模型没有生成：{generated}")

            self._stage(job_id, "验证原始几何", 0.76)
            strict_geometry = job["mode"] == "whole" or bool(params.get("strict_geometry"))
            raw_quality = inspect_game_mesh_quality(generated) if strict_geometry else inspect_model(generated)
            (job_dir / "raw_quality.json").write_text(
                json.dumps(raw_quality, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            if strict_geometry:
                require_ready_geometry(raw_quality)

            preserve_source = job["mode"] == "whole" or bool(params.get("preserve_geometry"))
            self._stage(job_id, "保持原始网格并导出" if preserve_source else "Blender 优化与统一导出", 0.82)
            final_model = job_dir / "model.glb"
            blender = settings.blender_binary()
            if blender is None:
                raise FileNotFoundError("Blender 未安装，无法完成游戏模型加工")
            if preserve_source:
                shutil.copy2(generated, final_model)
                log.write("保留 Pixal3D 原始 GLB 网格与材质，避免重新三角化造成的拓扑变化\n")
                log.flush()
            else:
                command = [
                    blender, "--background", "--python-exit-code", "1", "--python",
                    str(settings.root / "blender" / "prepare_asset.py"), "--",
                    "--input", str(generated), "--output", str(final_model),
                    "--target-faces", str(params["target_faces"]),
                ]
                self._command(command, cwd=job_dir, log=log)
            if not final_model.is_file() or final_model.stat().st_size == 0:
                raise FileNotFoundError(f"Blender 未输出有效 GLB：{final_model}")

            final_quality = (
                inspect_game_mesh_quality(final_model, baseline=raw_quality)
                if strict_geometry else inspect_model(final_model)
            )
            (job_dir / "processed_quality.json").write_text(
                json.dumps(final_quality, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            if strict_geometry:
                require_ready_geometry(final_quality)

            if final_model.stat().st_size > 8_000_000:
                self._stage(job_id, "生成浏览器轻量预览", 0.88)
                preview = job_dir / "preview.glb"
                resized = job_dir / "preview-textures.glb"
                node = settings.envs / "node22" / "bin" / "node"
                gltf_cli = settings.data_root / "tools" / "gltf-transform" / "node_modules" / "@gltf-transform" / "cli" / "bin" / "cli.js"
                if not node.is_file() or not gltf_cli.is_file():
                    raise FileNotFoundError("glTF Transform 尚未安装，执行 scripts/install-gltf-transform.sh")
                self._command(
                    [str(node), str(gltf_cli), "resize", str(final_model), str(resized),
                     "--width", "1024", "--height", "1024"],
                    cwd=job_dir, log=log, env={"PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", "")},
                )
                preview_quality = (
                    inspect_game_mesh_quality(resized, baseline=final_quality)
                    if strict_geometry else inspect_model(resized)
                )
                (job_dir / "preview_quality.json").write_text(
                    json.dumps(preview_quality, ensure_ascii=False, indent=2), encoding="utf-8",
                )
                if strict_geometry:
                    require_ready_geometry(preview_quality)
                if preview_quality["faces"] != final_quality["faces"] or preview_quality["non_manifold_edges"] != final_quality["non_manifold_edges"]:
                    raise ValueError("纹理预览处理修改了原始网格拓扑")
                self._command(
                    [str(node), str(gltf_cli), "meshopt", str(resized), str(preview),
                     "--level", "high", "--quantize-position", "16",
                     "--quantize-normal", "12", "--quantize-texcoord", "14"],
                    cwd=job_dir, log=log, env={"PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", "")},
                )
                if not preview.is_file() or preview.stat().st_size == 0:
                    raise FileNotFoundError("Meshopt 浏览器预览生成失败")
                resized.unlink()

            self._stage(job_id, "检查模型并打包 Godot 资源", 0.93)
            self._package(job, job_dir, final_model)
            self._stage(job_id, "Godot 场景创建与导入验证", 0.97)
            self._godot_stage(job, job_dir, log)
            self.store.update(job_id, status="completed", stage="completed", progress=1.0)

    def _godot_stage(self, job: dict[str, Any], job_dir: Path, log) -> None:
        executable = self.settings.godot_binary()
        if executable is None:
            raise FileNotFoundError("Godot 编辑器尚未安装")

        project = job_dir / "godot_project"
        asset = project / "assets" / "generated" / job["id"]
        scripts = project / "godot"
        asset.mkdir(parents=True, exist_ok=False)
        scripts.mkdir(parents=True, exist_ok=False)

        source_scripts = self.settings.root / "godot"
        for name in ("AssetStudioSceneBuilder.gd", "AssetStudioBatch.gd"):
            shutil.copy2(source_scripts / name, scripts / name)
        shutil.copy2(source_scripts / "project.godot", project / "project.godot")
        for name in ("model.glb", "manifest.json"):
            shutil.copy2(job_dir / name, asset / name)

        self._command([executable, "--headless", "--editor", "--path", str(project), "--import"], cwd=project, log=log)
        self._command(
            [executable, "--headless", "--path", str(project), "--script",
             "res://godot/AssetStudioBatch.gd", "--", job["id"]],
            cwd=project, log=log,
        )

        scene = asset / "game_asset.tscn"
        if not scene.is_file() or scene.stat().st_size == 0:
            raise FileNotFoundError("Godot 未生成有效的 game_asset.tscn")
        shutil.copy2(scene, job_dir / "game_asset.tscn")
        with zipfile.ZipFile(job_dir / "godot_asset.zip", "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(job_dir / "game_asset.tscn", arcname="game_asset.tscn")
        shutil.rmtree(project)

    def _package(self, job: dict[str, Any], job_dir: Path, final_model: Path) -> None:
        scene = trimesh.load(final_model, force="scene")
        geometries = [geometry for geometry in scene.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not geometries or sum(len(mesh.faces) for mesh in geometries) == 0:
            raise ValueError("GLB 无有效三角面，模型验收失败")
        gltf = GLTF2().load(str(final_model))
        quality = inspect_model(final_model)
        has_skeleton = quality["skinned"]
        if job["params"].get("rig") and not has_skeleton:
            raise ValueError("自动骨骼任务导出的 GLB 缺少 skin，模型验收失败")
        quality["bounds"] = scene.bounds.tolist()
        (job_dir / "quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = {
            "asset_id": job["id"], "title": job["title"], "type": job["kind"],
            "mode": job["mode"], "created_at": job["created_at"],
            "model": "model.glb", "scene": "game_asset.tscn", "engine": "Godot 4", "quality": quality,
            "rig_generated": has_skeleton,
            "animations_included": bool(gltf.animations),
            "image_model": job["params"].get("image_model", "wai"),
            "multi_views": bool(job["params"].get("multi_views", False)),
        }
        (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        included = ["model.glb", "quality.json", "manifest.json"]
        if (job_dir / "input.png").exists():
            included.append("input.png")
        for category in ("views", "candidates"):
            for image in sorted((job_dir / category).glob("*.png")):
                included.append(str(image.relative_to(job_dir)))
        for part in sorted((job_dir / "partcrafter" / job["id"]).glob("part_*.glb")):
            included.append(str(part.relative_to(job_dir)))
        bundle_path = job_dir / "godot_asset.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
            for relative in included:
                archive.write(job_dir / relative, arcname=relative)

