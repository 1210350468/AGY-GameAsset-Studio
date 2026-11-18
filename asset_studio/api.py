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
from asset_studio.quality_gate import assess_game_mesh_report, inspect_game_mesh_quality
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
    rig: bool = Form(False),
    num_parts: int = Form(3),
    seed: int = Form(42),
    image_steps: int = Form(30),
    target_faces: int = Form(50000),
    image_model: str = Form("qwen"),
    image_count: int = Form(1),
    multi_views: bool = Form(False),
    multi_view_strategy: str = Form("front-back"),
    pixal_low_vram: bool = Form(True),
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
    if multi_views and mode != "whole":
        raise HTTPException(400, "多视角建模需要使用 Pixal3D 完整模型")
    if multi_view_strategy not in {"front-back", "four"}:
        raise HTTPException(400, "未知的多视角建模方式")
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

    content = None
    if image is not None and image.filename:
        content = await image.read(25 * 1024 * 1024 + 1)
        if len(content) > 25 * 1024 * 1024 or not content:
            raise HTTPException(400, "参考图应为 25MB 以内的有效图片")
        from PIL import UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.width * original.height > 25_000_000:
                    raise HTTPException(400, "图片像素数超过 2500 万")
                processed = ImageOps.exif_transpose(original).convert("RGBA")
                output = io.BytesIO()
                processed.save(output, format="PNG")
                content = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise HTTPException(400, f"图片无法读取：{error}") from error
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
        "multi_view_strategy": multi_view_strategy,
        "pixal_low_vram": pixal_low_vram,
    }
    job_id = pipeline.create(title=title.strip(), kind=kind, mode=mode, params=params, input_bytes=content)
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


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
    return {"jobs": pipeline.store.list(limit=limit)}


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
        quality = inspect_game_mesh_quality(model) if job["mode"] == "whole" or job["params"].get("strict_geometry") else inspect_model(model)
        report = directory / "appearance_quality.json"
        if report.is_file():
            quality["appearance"] = json.loads(report.read_text(encoding="utf-8"))
        quality["visual_review_required"] = (
            job["kind"] in {"character", "monster"}
            and (job["status"] != "completed" or not report.is_file())
        )
        quality["quality_scope"] = "网格结构与原画轮廓；人物比例、服装结构和材质细节需要人工审核"
        return quality
    report = directory / "raw_quality.json"
    if report.is_file():
        return assess_game_mesh_report(json.loads(report.read_text(encoding="utf-8")))
    raise HTTPException(404, "尚未生成可检查的三维网格")


@app.get("/api/jobs/{job_id}/file/{file_name}")
def job_file(job_id: str, file_name: str) -> FileResponse:
    valid_files = {"model.glb", "preview.glb", "generated.glb", "godot_asset.zip", "game_asset.tscn", "input.png", "quality.json", "raw_quality.json", "processed_quality.json", "preview_quality.json", "appearance_quality.json", "manifest.json"}
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
    pipeline.store.update(job_id, status="completed", stage="外观已人工审核", progress=1.0)
    return {"job_id": job_id, "status": "completed"}


@app.post("/api/jobs/{job_id}/reject")
def reject_asset(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] != "review_required":
        raise HTTPException(409, "该资产当前没有等待审核")
    pipeline.store.update(job_id, status="rejected", stage="外观不符合要求", progress=1.0)
    return {"job_id": job_id, "status": "rejected"}


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
def reprocess(job_id: str, target_faces: int = Form(0)) -> dict:
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
        params={"rig": False, "target_faces": faces, "source_job": job_id},
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
            "quality": assess_game_mesh_report(json.loads(report.read_text(encoding="utf-8"))) if report.is_file() else None,
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

