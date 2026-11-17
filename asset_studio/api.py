import csv
import ctypes
import io
import os
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
import trimesh

from asset_studio.pipeline import AssetPipeline
from asset_studio.gpu import memory_headroom, require_gpu_headroom
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
    required = ("anime", "pixal3d", "blender")
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
) -> dict:
    if kind not in {"character", "monster", "weapon", "equipment", "prop", "scene"}:
        raise HTTPException(400, "资产类型无效")
    if mode not in {"whole", "parts"}:
        raise HTTPException(400, "建模模式无效")
    if rig and kind not in {"character", "monster"}:
        raise HTTPException(400, "自动骨骼仅支持角色和怪物")
    if not title.strip() or len(title) > 100 or len(prompt) > 3000:
        raise HTTPException(400, "标题或描述长度无效")
    if not (1 <= num_parts <= 16 and 1 <= image_steps <= 80 and 0 <= seed <= 2**32 - 1 and 1000 <= target_faces <= 500000):
        raise HTTPException(400, "生成参数超出范围")

    if mode == "whole":
        ensure_tool("pixal3d")
    else:
        ensure_tool("partcrafter")
    ensure_tool("blender")
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
        ensure_tool("anime")

    cuda = cuda_info()
    if not cuda["ready"]:
        raise HTTPException(503, cuda["diagnostic"])
    try:
        require_gpu_headroom(settings)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error

    params = {
        "prompt": prompt.strip(), "rig": rig, "num_parts": num_parts,
        "seed": seed, "image_steps": image_steps, "target_faces": target_faces,
    }
    job_id = pipeline.create(title=title.strip(), kind=kind, mode=mode, params=params, input_bytes=content)
    return {"job_id": job_id, "status": "queued", "url": f"/api/jobs/{job_id}"}


@app.post("/api/import", status_code=202)
async def import_model(
    file: UploadFile = File(...),
    title: str = Form(...),
    kind: str = Form("prop"),
    target_faces: int = Form(50000),
) -> dict:
    ensure_tool("blender")
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
    return get_job(job_id)


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: str) -> str:
    path = job_dir(job_id) / "process.log"
    return path.read_text(encoding="utf-8", errors="replace")[-100000:] if path.exists() else ""


@app.get("/api/jobs/{job_id}/file/{file_name}")
def job_file(job_id: str, file_name: str) -> FileResponse:
    valid_files = {"model.glb", "godot_asset.zip", "input.png", "quality.json", "manifest.json"}
    if file_name not in valid_files:
        raise HTTPException(404, "资源类型不存在")
    path = job_dir(job_id) / file_name
    if not path.is_file():
        raise HTTPException(404, "资源尚未生成")
    media_type = {"model.glb": "model/gltf-binary", "godot_asset.zip": "application/zip", "input.png": "image/png"}.get(file_name)
    return FileResponse(path, filename=file_name, media_type=media_type)


@app.get("/api/assets")
def list_assets() -> dict:
    return {"assets": [job for job in pipeline.store.list(limit=200) if job["status"] == "completed"]}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] not in {"failed", "completed"}:
        raise HTTPException(409, "任务正在执行")
    directory = settings.jobs_root / job_id
    suffix = ".glb" if job["mode"] == "import" else ".png"
    source = directory / f"input{suffix}"
    contents = source.read_bytes() if source.is_file() else None
    new_id = pipeline.create(
        title=job["title"], kind=job["kind"], mode=job["mode"],
        params=job["params"], input_bytes=contents,
    )
    return {"job_id": new_id, "status": "queued", "url": f"/api/jobs/{new_id}"}


app.mount("/", StaticFiles(directory=settings.root / "static", html=True), name="static")

