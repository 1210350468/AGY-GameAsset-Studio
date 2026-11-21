import csv
import ctypes
import html
import io
import json
import os
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
import trimesh

from asset_studio.pipeline import AssetPipeline
from asset_studio.image_models import IMAGE_MODELS, MODEL_LABELS, available_models
from asset_studio.quality_gate import inspect_game_mesh_quality
from asset_studio.quality_gate import require_ready_geometry
from asset_studio.gpu import memory_headroom
from asset_studio.quality import inspect_model
from asset_studio.settings import Settings


settings = Settings.from_environment()
pipeline = AssetPipeline(settings)


@asynccontextmanager
async def lifespan(application: FastAPI):
    pipeline.start()
    yield
    pipeline.close()


app = FastAPI(title="AGY 游戏资产工作台", version="0.1.0", lifespan=lifespan)


def get_job(job_id: str) -> dict:
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    job = pipeline.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def job_dir(job_id: str) -> Path:
    get_job(job_id)
    return settings.jobs_root / job_id


def ensure_tool(name: str) -> None:
    ready = pipeline.readiness()
    if not ready[name]["installed"]:
        raise HTTPException(status_code=503, detail=f"{name} 尚未安装，请运行 AutoDL 安装命令")


def ensure_multiview_ready() -> None:
    ensure_tool("pixal3d")
    required = (
        settings.pixal_repo / "inference_mv.py",
        settings.pixal_model_path / "pipeline_mv_cached_birefnet.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise HTTPException(status_code=503, detail=f"Pixal3D 多视图模型未安装完整：{missing}")


async def read_reference_image(upload: UploadFile) -> bytes:
    content = await upload.read(25 * 1024 * 1024 + 1)
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "参考图片须为 25MB 以内的有效图片")
    from PIL import UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.width * original.height > 25_000_000:
                raise HTTPException(400, "图片像素数超过 2500 万")
            converted = ImageOps.exif_transpose(original).convert("RGBA")
            output = io.BytesIO()
            converted.save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(400, f"图片无法读取：{error}") from error


def gpu_info() -> dict:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"available": False, "reason": "nvidia-smi 未安装", "devices": []}
    result = subprocess.run(
        [executable, "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        return {"available": False, "reason": result.stderr.strip(), "devices": []}
    devices = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) != 4:
            raise RuntimeError(f"GPU 状态格式异常：{row}")
        devices.append({"index": int(row[0]), "name": row[1].strip(), "memory_total_mib": int(row[2]), "memory_free_mib": int(row[3])})
    return {"available": bool(devices), "devices": devices}


def cuda_info() -> dict:
    if os.name != "posix":
        return {"ready": False, "code": None, "diagnostic": "CUDA 检查仅支持 Linux GPU 服务"}
    try:
        library = ctypes.CDLL("libcuda.so.1")
    except OSError as error:
        return {"ready": False, "code": None, "diagnostic": str(error)}
    code = library.cuInit(0)
    return {
        "ready": code == 0,
        "code": code,
        "diagnostic": "CUDA Driver 初始化成功" if code == 0 else f"CUDA Driver 初始化失败，错误码 {code}",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agy-game-asset-studio", "queue_length": pipeline.jobs.qsize()}


@app.get("/ready")
def ready() -> dict:
    tools = pipeline.readiness()
    required = ("anime", "pixal3d", "blender", "godot")
    missing = [name for name in required if not tools[name]["installed"]]
    if missing:
        raise HTTPException(status_code=503, detail={"missing": missing})
    gpu = gpu_info()
    if not gpu["available"]:
        raise HTTPException(status_code=503, detail={"gpu": gpu})
    cuda = cuda_info()
    if not cuda["ready"]:
        raise HTTPException(status_code=503, detail={"cuda": cuda})
    memory = memory_headroom(settings)
    if not memory["ready"]:
        raise HTTPException(status_code=503, detail={"gpu_headroom": memory})
    return {"status": "installed", "models": tools, "gpu": gpu, "cuda": cuda, "gpu_headroom": memory}


@app.get("/api/system")
def system() -> dict:
    disk = shutil.disk_usage(settings.data_root)
    return {
        "software": pipeline.readiness(),
        "gpu": gpu_info(),
        "cuda": cuda_info(),
        "gpu_headroom": memory_headroom(settings),
        "storage": {"path": str(settings.data_root), "free_gb": round(disk.free / (1024 ** 3), 1)},
        "queue_length": pipeline.jobs.qsize(),
    }


@app.get("/api/config")
def config() -> dict:
    return {
        "checkpoint": settings.checkpoint,
        "pixal_low_vram": settings.pixal_low_vram,
        "comfy_url": settings.comfy_url,
        "default_engine": "Godot 4",
        "pixal_multiview_ready": all(path.is_file() for path in (
            settings.pixal_repo / "inference_mv.py",
            settings.pixal_model_path / "pipeline_mv_cached_birefnet.json",
        )),
        "modes": ["whole", "parts"],
        "image_models": [
            {"id": model, "name": MODEL_LABELS[model], "available": available_models(settings)[model]}
            for model in IMAGE_MODELS
        ],
    }


@app.post("/api/jobs", status_code=202)
async def create_job(
    title: str = Form(...),
    kind: str = Form("character"),
    prompt: str = Form(""),
    mode: str = Form("whole"),
    image: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    right: UploadFile | None = File(None),
    left: UploadFile | None = File(None),
    rig: bool = Form(False),
    num_parts: int = Form(3),
    seed: int = Form(42),
    image_steps: int = Form(30),
    target_faces: int = Form(50000),
    image_model: str = Form("qwen"),
    image_count: int = Form(1),
    quality_target: str = Form("prototype"),
    multi_views: bool = Form(False),
    multi_view_strategy: str = Form("front-back"),
    pixal_low_vram: bool = Form(True),
    clean_floor_shadow: bool = Form(True),
) -> dict:
    if kind not in {"character", "monster", "weapon", "equipment", "prop", "scene"}:
        raise HTTPException(400, "资产类型无效")
    if mode not in {"whole", "parts"}:
        raise HTTPException(400, "建模模式无效")
    if rig and kind not in {"character", "monster"}:
        raise HTTPException(400, "自动骨骼仅支持角色和怪物")
    if image_model not in IMAGE_MODELS:
        raise HTTPException(400, "原画模型无效")
    if image_count not in {1, 4}:
        raise HTTPException(400, "原画候选数需为 1 张或 4 张")
    if quality_target not in {"prototype", "production"}:
        raise HTTPException(400, "游戏资产制作类型无效")
    if multi_views and mode != "whole":
        raise HTTPException(400, "多视角建模需要使用 Pixal3D 完整模型")
    if multi_view_strategy not in {"front-back", "four"}:
        raise HTTPException(400, "未知的多视角建模方式")
    supplied_views = {name: upload for name, upload in (
        ("back", back), ("right", right), ("left", left)
    ) if upload is not None and upload.filename}
    if quality_target == "production" and (
        mode != "whole"
        or not multi_views
        or multi_view_strategy != "four"
        or set(supplied_views) != {"back", "right", "left"}
        or image is None
        or not image.filename
    ):
        raise HTTPException(
            400,
            "正式游戏建模要求上传同一资产的正面、右面、背面、左面四张独立参考图，"
            "并启用 Pixal3D 四视角。单图与自动猜测视角归入概念实验。",
        )
    if supplied_views and not multi_views:
        raise HTTPException(400, "上传多视角参考图时须开启 Pixal3D 多视角")
    if supplied_views:
        expected = {"back"} if multi_view_strategy == "front-back" else {"right", "back", "left"}
        if set(supplied_views) != expected or image is None or not image.filename:
            raise HTTPException(400, f"多视图参考图需要 front 原画及 {sorted(expected)}")
    if not title.strip() or len(title) > 100 or len(prompt) > 3000:
        raise HTTPException(400, "标题或描述长度无效")
    if not (1 <= num_parts <= 16 and 1 <= image_steps <= 80 and 0 <= seed <= 2**32 - 1 and 1000 <= target_faces <= 500000):
        raise HTTPException(400, "生成参数超出范围")

    if mode == "whole":
        ensure_tool("pixal3d")
    else:
        ensure_tool("partcrafter")
    ensure_tool("blender")
    ensure_tool("godot")
    if rig:
        ensure_tool("skintokens")
    if multi_views:
        ensure_multiview_ready()

    content = None
    if image is not None and image.filename:
        content = await read_reference_image(image)
    reference_views = None
    if supplied_views:
        reference_views = {"front": content}
        for name, upload in supplied_views.items():
            reference_views[name] = await read_reference_image(upload)
    if content is None:
        if not prompt.strip():
            raise HTTPException(400, "请输入原画描述或上传参考图片")
        if image_model == "wai":
            ensure_tool("anime")
        elif not available_models(settings)[image_model]:
            raise HTTPException(503, f"原画模型 {MODEL_LABELS[image_model]} 尚未配置完成")

    cuda = cuda_info()
    if not cuda["ready"]:
        raise HTTPException(503, cuda["diagnostic"])
    params = {
        "prompt": prompt.strip(), "rig": rig, "num_parts": num_parts,
        "seed": seed, "image_steps": image_steps, "target_faces": target_faces,
        "image_model": image_model, "image_count": image_count, "multi_views": multi_views,
        "quality_target": quality_target,
        "reference_origin": "explicit_four_view" if quality_target == "production" else "experimental",
        "multi_view_strategy": multi_view_strategy,
        "pixal_low_vram": pixal_low_vram,
        "clean_floor_shadow": clean_floor_shadow if kind == "monster" else False,
    }
    job_id = pipeline.create(
        title=title.strip(), kind=kind, mode=mode, params=params,
        input_bytes=content, reference_views=reference_views,
    )
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


@app.post("/api/jobs/{job_id}/rebuild-multiview", status_code=202)
async def rebuild_multiview(
    job_id: str,
    multi_view_strategy: str = Form("front-back"),
    pixal_low_vram: bool = Form(True),
    back: UploadFile | None = File(None),
    right: UploadFile | None = File(None),
    left: UploadFile | None = File(None),
) -> dict:
    source = get_job(job_id)
    if source["status"] in {"running", "queued"}:
        raise HTTPException(409, "原始建模任务正在执行")
    if multi_view_strategy not in {"front-back", "four"}:
        raise HTTPException(400, "只支持正反双视角或正右背左四视角")
    ensure_multiview_ready()
    ensure_tool("blender")
    ensure_tool("godot")
    directory = job_dir(job_id)
    reference = directory / "input.png"
    if not reference.is_file():
        raise HTTPException(409, "原任务没有原画，请先上传参考图片")
    provided = {name: upload for name, upload in (
        ("back", back), ("right", right), ("left", left)
    ) if upload is not None and upload.filename}
    expected = ("front", "back") if multi_view_strategy == "front-back" else ("front", "right", "back", "left")
    stored = {
        name: (directory / "views" / f"{name}.png").read_bytes()
        for name in expected if (directory / "views" / f"{name}.png").is_file()
    }
    stored["front"] = reference.read_bytes()
    for name, upload in provided.items():
        if name not in expected:
            raise HTTPException(400, f"{name} 视角与所选模式不符")
        stored[name] = await read_reference_image(upload)
    if provided and set(stored) != set(expected):
        raise HTTPException(400, f"缺少多视角原画：{sorted(set(expected) - set(stored))}")
    params = dict(source["params"])
    params.update({
        "multi_views": True,
        "multi_view_strategy": multi_view_strategy,
        "pixal_low_vram": pixal_low_vram,
        "rig": False,
        "source_job": job_id,
        "seed": (int(params.get("seed", 42)) + 1) % (2 ** 32),
    })
    views = stored if set(stored) == set(expected) else None
    new_id = pipeline.create(
        title=source["title"] + " · Pixal3D 多视图增强",
        kind=source["kind"], mode="whole", params=params,
        input_bytes=stored["front"], reference_views=views,
    )
    return {"job_id": new_id, "status": "queued", "url": f"/api/jobs/{new_id}"}


@app.post("/api/jobs/{job_id}/repair-ground", status_code=202)
def repair_monster_ground(job_id: str) -> dict:
    original = get_job(job_id)
    if original["kind"] != "monster" or original["mode"] != "whole":
        raise HTTPException(400, "脚底地面重建适用于 Pixal3D 怪物任务")
    if original["status"] in {"running", "queued"}:
        raise HTTPException(409, "原任务还在执行")
    source = job_dir(job_id) / "input.png"
    if not source.is_file():
        raise HTTPException(409, "原任务缺少参考原画")
    ensure_tool("pixal3d")
    ensure_tool("blender")
    ensure_tool("godot")
    params = dict(original["params"])
    params.update({
        "source_job": job_id,
        "clean_floor_shadow": True,
        "multi_views": False,
        "rig": False,
        "pixal_low_vram": True,
        "seed": (int(params.get("seed", 42)) + 1) % (2 ** 32),
    })
    repaired_id = pipeline.create(
        title=original["title"] + " · 脚底地面重建",
        kind="monster", mode="whole", params=params,
        input_bytes=source.read_bytes(),
    )
    return {"job_id": repaired_id, "status": "queued", "url": f"/api/jobs/{repaired_id}"}


@app.post("/api/jobs/{job_id}/repair-ground-mesh", status_code=202)
def repair_monster_ground_mesh(
    job_id: str,
    height_ratio: float = Form(0.035),
) -> dict:
    original = get_job(job_id)
    if original["kind"] != "monster" or original["status"] in {"queued", "running"}:
        raise HTTPException(409, "仅支持已生成的怪物模型")
    if not 0.01 <= height_ratio <= 0.055:
        raise HTTPException(400, "脚底裁切高度须在模型高度的 1%～5.5%")
    source = job_dir(job_id) / "model.glb"
    if not source.is_file():
        raise HTTPException(409, "原任务缺少 GLB")
    original_quality = inspect_game_mesh_quality(source, profile="monster")
    if not original_quality["ground_artifacts"]["ground_anomaly_detected"]:
        raise HTTPException(409, "当前模型未检测到需要裁切的脚底地面")
    if original_quality["skinned"]:
        raise HTTPException(409, "已绑定骨骼的怪物需要在绑定之前处理网格")
    blender = settings.blender_binary()
    if blender is None:
        raise HTTPException(503, "Blender 未安装")
    output = settings.data_root / "ground_repairs" / (uuid.uuid4().hex + ".glb")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        blender, "--background", "--python-exit-code", "1", "--python",
        str(settings.root / "blender" / "repair_ground_base.py"), "--",
        "--input", str(source), "--output", str(output),
        "--height-ratio", str(height_ratio),
    ], stdin=subprocess.DEVNULL, timeout=settings.timeout_seconds, check=True)
    quality = inspect_game_mesh_quality(output, profile="monster")
    original_ground = original_quality["ground_artifacts"]["ground_footprint_area_ratio"]
    repaired_ground = quality["ground_artifacts"]["ground_footprint_area_ratio"]
    if repaired_ground >= 0.075 or original_ground - repaired_ground < 0.04:
        raise ValueError(f"地面修复未达到要求：{original_ground:.2%} → {repaired_ground:.2%}")
    if quality["images"] != original_quality["images"] or quality["faces"] < original_quality["faces"] * 0.8:
        raise ValueError("脚底地面裁切损坏了材质或主体结构")
    reference = job_dir(job_id) / "input.png"
    params = {
        **original["params"],
        "rig": False,
        "strict_geometry": True,
        "preserve_geometry": True,
        "source_job": job_id,
        "ground_repair_height_ratio": height_ratio,
        "ground_ratio_before": original_ground,
        "ground_ratio_after": repaired_ground,
    }
    repaired_id = pipeline.create(
        title=original["title"] + " · 地面网格清理候选",
        kind="monster", mode="import", params=params,
        input_bytes=output.read_bytes(),
        reference_image_bytes=reference.read_bytes() if reference.is_file() else None,
    )
    return {
        "job_id": repaired_id, "status": "queued",
        "url": f"/api/jobs/{repaired_id}",
        "ground_footprint_before": original_ground,
        "ground_footprint_after": repaired_ground,
    }


@app.post("/api/nextgen/build", status_code=202)
def build_gallery_views(
    title: str = Form("流亡战士 · Qwen 四视角重建"),
    kind: str = Form("character"),
    target_faces: int = Form(250000),
) -> dict:
    if kind not in {"character", "monster"} or not title.strip() or len(title) > 100:
        raise HTTPException(400, "资产信息无效")
    if not 1000 <= target_faces <= 500000:
        raise HTTPException(400, "目标三角面数无效")
    ensure_tool("pixal3d")
    ensure_tool("blender")
    ensure_tool("godot")
    root = settings.data_root / "validation-assets" / "nextgen" / "qwen"
    views = {}
    for name in ("front", "right", "back", "left"):
        matches = sorted((root / name).glob("*.png"))
        if len(matches) != 1:
            raise HTTPException(409, f"参考图 {name} 需要恰好一张已完成原画")
        path = matches[0]
        with Image.open(path) as image:
            image.verify()
        views[name] = path.read_bytes()
    job_id = pipeline.create(
        title=title.strip(), kind=kind, mode="whole",
        params={
            "prompt": "同一位暗黑奇幻流亡战士，完整角色，保持装备一致",
            "rig": False, "num_parts": 3, "seed": 20261118,
            "image_steps": 28, "target_faces": target_faces,
            "image_model": "qwen", "image_count": 1, "multi_views": True,
            "multi_view_strategy": "four",
            "pixal_low_vram": True,
            "source_gallery": True,
        },
        input_bytes=views["front"], reference_views=views,
    )
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


@app.post("/api/import", status_code=202)
async def import_model(
    file: UploadFile = File(...),
    title: str = Form(...),
    kind: str = Form("prop"),
    target_faces: int = Form(50000),
) -> dict:
    ensure_tool("blender")
    ensure_tool("godot")
    if kind not in {"character", "monster", "weapon", "equipment", "prop", "scene"}:
        raise HTTPException(400, "资产类型无效")
    if not title.strip() or len(title) > 100 or not (1000 <= target_faces <= 500000):
        raise HTTPException(400, "标题或目标三角面数无效")
    if Path(file.filename or "").suffix.lower() != ".glb":
        raise HTTPException(400, "请上传 .glb 模型")
    payload = await file.read(250 * 1024 * 1024 + 1)
    if not payload or len(payload) > 250 * 1024 * 1024:
        raise HTTPException(400, "GLB 文件大小应在 250MB 以内")
    try:
        scene = trimesh.load(io.BytesIO(payload), file_type="glb", force="scene")
        if len(scene.geometry) == 0:
            raise ValueError("GLB 不包含几何体")
    except (ValueError, OSError, IndexError) as error:
        raise HTTPException(400, f"GLB 解析失败：{error}") from error
    job_id = pipeline.create(
        title=title.strip(), kind=kind, mode="import",
        params={"rig": False, "target_faces": target_faces}, input_bytes=payload,
    )
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"jobs": [
        {
            **job,
            "has_preview": (settings.jobs_root / job["id"] / "input.png").is_file(),
        }
        for job in pipeline.store.list(limit=limit)
    ]}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    directory = job_dir(job_id)
    return {
        **job,
        "has_preview": (directory / "input.png").is_file(),
        "has_fast_preview": (directory / "preview.glb").is_file(),
        "appearance_report_available": (directory / "appearance_quality.json").is_file(),
    }


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: str) -> str:
    path = job_dir(job_id) / "process.log"
    return path.read_text(encoding="utf-8", errors="replace")[-100000:] if path.exists() else ""


@app.get("/api/jobs/{job_id}/inspect")
def inspect_job(job_id: str) -> dict:
    job = get_job(job_id)
    directory = job_dir(job_id)
    model = directory / "model.glb"
    if model.is_file():
        quality = inspect_game_mesh_quality(model, profile=job["kind"]) if job["mode"] == "whole" or job["params"].get("strict_geometry") else inspect_model(model)
        report = directory / "appearance_quality.json"
        if report.is_file():
            quality["appearance"] = json.loads(report.read_text(encoding="utf-8"))
        texture_report = directory / "texture_repair.json"
        if texture_report.is_file():
            quality["texture_repair"] = json.loads(texture_report.read_text(encoding="utf-8"))
        quality["visual_review_required"] = (
            job["kind"] in {"character", "monster"}
            and (job["status"] != "completed" or not report.is_file())
        )
        quality["quality_scope"] = "网格结构与原画轮廓；人物比例、服装结构和材质细节需要人工审核"
        return quality
    report = directory / "raw_quality.json"
    if report.is_file():
        original = next(
            (path for path in (
                directory / "generated.glb", directory / "rigged.glb", directory / "input.glb"
            ) if path.is_file()), None,
        )
        if original is None:
            raise HTTPException(404, "原始三维模型文件不存在")
        return inspect_game_mesh_quality(original, profile=job["kind"])
    raise HTTPException(404, "尚未生成可检查的三维网格")


@app.get("/api/jobs/{job_id}/file/{file_name}")
def job_file(job_id: str, file_name: str) -> FileResponse:
    valid_files = {"model.glb", "preview.glb", "generated.glb", "godot_asset.zip", "game_asset.tscn", "input.png", "quality.json", "raw_quality.json", "processed_quality.json", "preview_quality.json", "appearance_quality.json", "texture_repair.json", "manifest.json"}
    if file_name not in valid_files:
        raise HTTPException(404, "资源类型不存在")
    path = job_dir(job_id) / file_name
    if not path.is_file():
        raise HTTPException(404, "资源尚未生成")
    media_type = {"model.glb": "model/gltf-binary", "preview.glb": "model/gltf-binary", "generated.glb": "model/gltf-binary", "godot_asset.zip": "application/zip", "input.png": "image/png"}.get(file_name)
    return FileResponse(path, filename=file_name, media_type=media_type)


@app.get("/api/jobs/{job_id}/images/{image_name}")
def job_reference_image(job_id: str, image_name: str) -> FileResponse:
    if image_name in {"front", "back", "left", "right"}:
        path = job_dir(job_id) / "views" / f"{image_name}.png"
    elif image_name in {f"candidate-{number}" for number in range(1, 5)}:
        path = job_dir(job_id) / "candidates" / f"{image_name}.png"
    else:
        raise HTTPException(404, "参考图名称无效")
    if not path.is_file():
        raise HTTPException(404, "参考图尚未生成")
    return FileResponse(path, media_type="image/png")


@app.get("/api/jobs/{job_id}/references", response_class=HTMLResponse)
def job_references(job_id: str) -> str:
    job = get_job(job_id)
    root = job_dir(job_id)
    images = [
        (key, root / "views" / f"{key}.png") for key in ("front", "right", "back", "left")
    ] + [
        (key, root / "candidates" / f"{key}.png") for key in ("candidate-1", "candidate-2", "candidate-3", "candidate-4")
    ]
    items = "".join(
        f'<article><a href="/api/jobs/{job_id}/images/{key}" target="_blank">'
        f'<img loading="lazy" src="/api/jobs/{job_id}/images/{key}" alt="{key}"></a>'
        f'<p>{html.escape(key)}</p></article>'
        for key, path in images if path.is_file()
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<title>{html.escape(job["title"])} · 参考原画</title><style>'
        'body{font-family:system-ui,Microsoft YaHei,sans-serif;background:#f3f5fa;color:#233;margin:28px}'
        'main{max-width:1400px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}'
        'article{background:white;padding:12px;border-radius:12px;box-shadow:0 4px 15px #0001}'
        'img{width:100%;height:340px;object-fit:contain;background:#eef1f6}p{font-size:13px}'
        '</style></head><body><main>'
        f'<h1>{html.escape(job["title"])}</h1><p>原画候选与四视角真实生成结果</p>'
        f'<div class="grid">{items}</div></main></body></html>'
    )


@app.get("/api/assets")
def list_assets() -> dict:
    return {"assets": [
        {
            **job,
            "has_preview": (settings.jobs_root / job["id"] / "input.png").is_file(),
            "has_fast_preview": (settings.jobs_root / job["id"] / "preview.glb").is_file(),
        }
        for job in pipeline.store.list(limit=200) if job["status"] in {"completed", "review_required", "rejected"}
    ]}


@app.post("/api/jobs/{job_id}/approve")
def approve_asset(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] != "review_required":
        raise HTTPException(409, "该资产当前没有等待审核")
    directory = job_dir(job_id)
    if not (directory / "godot_asset.zip").is_file():
        raise HTTPException(409, "Godot 资源包尚未完成")
    processed = directory / "processed_quality.json"
    if processed.is_file():
        quality = json.loads(processed.read_text(encoding="utf-8"))
        if quality.get("game_ready") is False:
            raise HTTPException(409, "模型网格仍有待修复问题：" + "；".join(quality["game_readiness_reasons"]))
    pipeline.store.update(job_id, status="completed", stage="外观已人工审核", progress=1.0)
    return {"job_id": job_id, "status": "completed"}


@app.post("/api/jobs/{job_id}/reject")
def reject_asset(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] != "review_required":
        raise HTTPException(409, "该资产当前没有等待审核")
    pipeline.store.update(job_id, status="rejected", stage="外观不符合要求", progress=1.0)
    return {"job_id": job_id, "status": "rejected"}


@app.post("/api/jobs/{job_id}/repair-texture", status_code=202)
def repair_asset_texture(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] not in {"completed", "review_required", "rejected"}:
        raise HTTPException(409, "请选择已生成完整模型的资产")
    if job["kind"] not in {"character", "monster"}:
        raise HTTPException(400, "此操作适用于角色或怪物的贴图残留修复")
    source_dir = job_dir(job_id)
    source = source_dir / "model.glb"
    if not source.is_file():
        raise HTTPException(404, "原始 GLB 不存在")
    reference = source_dir / "input.png"
    ensure_tool("blender")
    ensure_tool("godot")
    new_id = pipeline.create(
        title=f"{job['title']} · 贴图残留修复",
        kind=job["kind"], mode="import",
        params={
            "rig": False, "target_faces": 500000, "strict_geometry": True,
            "preserve_geometry": True, "repair_texture": True,
            "source_job": job_id, "image_model": job["params"].get("image_model", "qwen"),
        },
        input_bytes=source.read_bytes(),
        reference_image_bytes=reference.read_bytes() if reference.is_file() else None,
    )
    return {"job_id": new_id, "status": "queued", "url": f"/api/jobs/{new_id}"}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] not in {"failed", "completed", "review_required", "rejected"}:
        raise HTTPException(409, "任务正在执行")
    directory = settings.jobs_root / job_id
    suffix = ".glb" if job["mode"] == "import" else ".png"
    source = directory / f"input{suffix}"
    contents = source.read_bytes() if source.is_file() else None
    original_views = {
        name: (directory / "views" / f"{name}.png").read_bytes()
        for name in ("front", "right", "back", "left")
        if (directory / "views" / f"{name}.png").is_file()
    }
    params = dict(job["params"])
    if job["status"] == "rejected":
        params["seed"] = (int(params.get("seed", 42)) + 1) % (2 ** 32)
    new_id = pipeline.create(
        title=job["title"], kind=job["kind"], mode=job["mode"],
        params=params, input_bytes=contents,
        reference_image_bytes=(directory / "input.png").read_bytes()
        if job["mode"] == "import" and (directory / "input.png").is_file() else None,
        reference_views=original_views or None,
    )
    return {"job_id": new_id, "status": "queued", "url": f"/api/jobs/{new_id}"}


@app.post("/api/jobs/{job_id}/reprocess", status_code=202)
def reprocess(
    job_id: str, target_faces: int = Form(0),
    preserve_geometry: bool = Form(False),
) -> dict:
    job = get_job(job_id)
    if job["status"] not in {"completed", "failed", "review_required", "rejected"}:
        raise HTTPException(409, "请选择已经完成或执行失败的资产任务")
    source_dir = job_dir(job_id)
    candidates = (
        source_dir / "rigged.glb",
        source_dir / "generated.glb",
        source_dir / "partcrafter" / job_id / "object.glb",
        source_dir / "model.glb",
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise HTTPException(404, "任务缺少可优化的三维模型")
    high_detail_source = (source_dir / "rigged.glb").is_file() or (source_dir / "generated.glb").is_file()
    faces = target_faces or (250000 if high_detail_source else 50000)
    if not 1000 <= faces <= 500000:
        raise HTTPException(400, "目标三角面数需在 1000 至 500000 之间")
    reference_path = source_dir / "input.png"
    reference_image = reference_path.read_bytes() if reference_path.is_file() else None
    new_id = pipeline.create(
        title=f"{job['title']} · 网格优化",
        kind=job["kind"], mode="import",
        params={
            "rig": False, "target_faces": faces, "source_job": job_id,
            "preserve_geometry": preserve_geometry,
            "strict_geometry": preserve_geometry,
        },
        input_bytes=source.read_bytes(), reference_image_bytes=reference_image,
    )
    return {"job_id": new_id, "status": "queued", "url": f"/api/jobs/{new_id}"}


@app.get("/api/nextgen/previews")
def nextgen_previews() -> dict:
    root = settings.data_root / "validation-assets" / "nextgen"
    if not root.is_dir():
        return {"images": []}
    images = sorted(root.rglob("*.png"), key=lambda path: (path.parent.as_posix(), path.name))
    return {"images": [
        {
            "path": image.relative_to(root).as_posix(),
            "url": f"/api/nextgen/images/{image.relative_to(root).as_posix()}",
            "size_bytes": image.stat().st_size,
        }
        for image in images if image.is_file()
    ]}


@app.get("/api/nextgen/experiments")
def nextgen_experiments() -> dict:
    root = settings.data_root / "validation-assets" / "pixal-input-fix-20261119"
    experiments = []
    for mode in ("single", "front-back", "four"):
        directory = root / mode
        report = directory / "raw_quality.json"
        geometry = directory / "generated.glb"
        experiments.append({
            "mode": mode,
            "finished": report.is_file() and geometry.is_file(),
            "quality": inspect_game_mesh_quality(geometry, profile="character")
            if report.is_file() and geometry.is_file() else None,
            "model_url": f"/api/nextgen/experiments/{mode}/model.glb" if geometry.is_file() and report.is_file() else None,
        })
    return {"experiments": experiments}


@app.get("/api/nextgen/experiments/{mode}/model.glb")
def nextgen_experiment_model(mode: str) -> FileResponse:
    if mode not in {"single", "front-back", "four"}:
        raise HTTPException(404, "未知实验")
    directory = settings.data_root / "validation-assets" / "pixal-input-fix-20261119" / mode
    model = directory / "generated.glb"
    if not model.is_file() or not (directory / "raw_quality.json").is_file():
        raise HTTPException(404, "实验模型尚未完成")
    return FileResponse(model, filename=f"pixal3d-{mode}.glb", media_type="model/gltf-binary")


@app.post("/api/nextgen/experiments/{mode}/package", status_code=202)
def package_nextgen_experiment(mode: str) -> dict:
    if mode not in {"single", "front-back", "four"}:
        raise HTTPException(404, "未知实验")
    directory = settings.data_root / "validation-assets" / "pixal-input-fix-20261119" / mode
    source = directory / "generated.glb"
    if not source.is_file() or not (directory / "raw_quality.json").is_file():
        raise HTTPException(409, "实验重建尚未完成")
    quality = inspect_game_mesh_quality(source)
    if not quality["game_ready"]:
        raise HTTPException(409, "原始网格不符合游戏资产质量要求：" + "；".join(quality["game_readiness_reasons"]))
    ensure_tool("blender")
    ensure_tool("godot")
    reference = settings.jobs_root / "fb581d2bbd534dec9fe2219f1f3e1776" / "input.png"
    job_id = pipeline.create(
        title=f"流亡战士 · Pixal3D {mode} 校验模型",
        kind="character", mode="import",
        params={
            "rig": False, "target_faces": 500000,
            "image_model": "qwen", "multi_views": mode != "single",
            "strict_geometry": True, "preserve_geometry": True,
            "source_experiment": mode,
        },
        input_bytes=source.read_bytes(),
        reference_image_bytes=reference.read_bytes() if reference.is_file() else None,
    )
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


@app.get("/api/nextgen/images/{image_path:path}")
def nextgen_image(image_path: str) -> FileResponse:
    root = (settings.data_root / "validation-assets" / "nextgen").resolve()
    image = (root / image_path).resolve()
    if not image.is_relative_to(root) or image.suffix.lower() != ".png" or not image.is_file():
        raise HTTPException(404, "参考原画不存在")
    return FileResponse(image, media_type="image/png")


@app.get("/nextgen")
def nextgen_gallery() -> FileResponse:
    return FileResponse(settings.root / "static" / "nextgen.html", media_type="text/html")


app.mount("/", StaticFiles(directory=settings.root / "static", html=True), name="static")

