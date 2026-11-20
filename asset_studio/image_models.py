import base64
import io
import os
import shutil
from pathlib import Path

import httpx
from PIL import Image

from asset_studio.comfy import generate_image
from asset_studio.nextgen import (
    anima_candidates_workflow,
    qwen_character_view_workflow,
    qwen_concept_workflow,
    require_gpu_headroom,
    submit_and_download,
    upload_reference,
    validate_installed_nodes,
)


IMAGE_MODELS = ("qwen", "anima", "wai", "gpt-image")
MODEL_LABELS = {
    "qwen": "Qwen-Image 2.1",
    "anima": "Anima 2.9B",
    "wai": "WAI Illustrious v17",
    "gpt-image": "GPT Image 2.5 Flare",
}
NEXTGEN_PORTS = {"qwen": 8190, "anima": 8189}


def available_models(settings) -> dict:
    return {
        "qwen": (settings.sources / "ComfyUI-v0.37.4" / "models" / "diffusion_models" / "qwen_image_2.1_bf16.safetensors").is_file(),
        "anima": (settings.sources / "ComfyUI-v0.37.4" / "models" / "diffusion_models" / "Anima-2.9B-preview-v1.safetensors").is_file(),
        "wai": settings.image_checkpoint.is_file(),
        "gpt-image": bool(os.environ.get("OPENAI_API_KEY")),
    }


def _save_gpt_image(prompt: str, destination: Path, kind: str, log) -> None:
    token = os.environ.get("OPENAI_API_KEY")
    if not token:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 GPT Image")
    prompt = (
        f"Create one highly detailed dark fantasy action RPG game asset concept illustration. {prompt}. "
        "Complete visible subject, clean silhouette, single isolated subject, neutral pose, "
        "studio lighting, white background, consistent materials and believable construction."
    )
    payload = {
        "model": "gpt-image-2.5-flare", "prompt": prompt,
        "size": "1024x1536" if kind in {"character", "monster"} else "1024x1024",
        "quality": "high", "output_format": "png", "n": 1,
    }
    with httpx.Client(timeout=600) as client:
        response = client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {token}"}, json=payload,
        )
        response.raise_for_status()
        images = response.json()["data"]
        if len(images) != 1:
            raise RuntimeError("GPT Image 返回图片数量错误")
        contents = base64.b64decode(images[0]["b64_json"], validate=True)
        with Image.open(io.BytesIO(contents)) as generated:
            generated.verify()
        destination.write_bytes(contents)
    log.write(f"GPT Image output saved: {destination}\n")
    log.flush()


def render_concept(
    *, settings, model: str, prompt: str, kind: str, seed: int, steps: int,
    candidates: int, destination: Path, log,
) -> list[Path]:
    if model not in IMAGE_MODELS:
        raise ValueError("原画模型无效")
    if candidates not in {1, 4}:
        raise ValueError("候选数量只支持 1 张或 4 张")
    directory = destination.parent / "candidates"
    directory.mkdir(exist_ok=True)
    if model == "wai":
        for index in range(candidates):
            generate_image(
                base_url=settings.comfy_url, checkpoint=settings.checkpoint,
                prompt=prompt, destination=directory / f"candidate-{index + 1}.png",
                kind=kind, seed=seed + index, steps=steps,
                timeout_seconds=settings.timeout_seconds, log=log,
            )
    elif model == "gpt-image":
        for index in range(candidates):
            _save_gpt_image(prompt, directory / f"candidate-{index + 1}.png", kind, log)
    else:
        gpu_file = settings.data_root / f"nextgen-{model}-gpu"
        gpu_index = int(gpu_file.read_text(encoding="utf-8").strip())
        endpoint = f"http://127.0.0.1:{NEXTGEN_PORTS[model]}"
        validate_installed_nodes(endpoint, model)
        require_gpu_headroom(model, gpu_index)
        if model == "anima":
            workflow = anima_candidates_workflow(prompt, seed, count=candidates)
            workflow["7"]["inputs"]["steps"] = steps
            generated = submit_and_download(
                endpoint, workflow, "9", directory, candidates, model, gpu_index,
                timeout_seconds=settings.timeout_seconds,
            )
            for index, path in enumerate(generated):
                path.rename(directory / f"candidate-{index + 1}.png")
        else:
            for index in range(candidates):
                workflow = qwen_concept_workflow(
                    f"One full-body {kind} for a polished dark fantasy action role playing game. "
                    f"{prompt}. Single subject, centered orthographic front character reference, "
                    "neutral modeling A-pose, arms visibly separated from torso, both legs fully visible and separated, "
                    "cloak hangs behind the body with clear shoulder attachments, no loose cloth covering legs, "
                    "feet grounded, complete equipment, realistic anatomy, plain white studio background, "
                    "no floating accessories, no dramatic camera perspective, professional 3D model reference.",
                    seed + index, steps,
                )
                generated = submit_and_download(
                    endpoint, workflow, "7", directory, 1, model, gpu_index,
                    timeout_seconds=settings.timeout_seconds,
                )
                generated[0].rename(directory / f"candidate-{index + 1}.png")

    saved = [directory / f"candidate-{index + 1}.png" for index in range(candidates)]
    for image in saved:
        with Image.open(image) as source:
            source.verify()
    shutil.copy2(saved[0], destination)
    log.write(f"Selected candidate 1 / {len(saved)} for Pixal3D: {destination}\n")
    log.flush()
    return saved


def render_reference_views(
    settings, source: Path, prompt: str, output: Path, seed: int, log,
    view_names: tuple[str, ...] = ("front", "back"),
    kind: str = "character",
) -> list[Path]:
    if view_names not in {("front", "back"), ("front", "right", "back", "left")}:
        raise ValueError("多视角模式需为正反双视角或标准四视角")
    gpu_index = int((settings.data_root / "nextgen-qwen-gpu").read_text(encoding="utf-8").strip())
    endpoint = f"http://127.0.0.1:{NEXTGEN_PORTS['qwen']}"
    validate_installed_nodes(endpoint, "qwen")
    require_gpu_headroom("qwen", gpu_index)
    uploaded = upload_reference(endpoint, source)
    saved = []
    perspectives = {"right": "right side", "back": "back", "left": "left side"}
    geometry = {
        "character": "Keep the exact neutral pose, body proportions, clothing layers, boots, hands, weapons, attachments and anatomy.",
        "monster": "Keep the exact anatomy, stance, number of limbs, appendages, head shape, armor and tail attachments.",
        "weapon": "Keep the exact blade, grip, guard, handle, pommel, material layers, ornament positions and physical proportions.",
        "equipment": "Keep the exact armor structure, straps, buckles, fasteners, layered materials and mounting points.",
        "prop": "Keep the exact assembly, silhouette, mechanical construction, carved details, material colors and physical proportions.",
        "scene": "Keep the exact architectural structure, entrances, floor boundaries, spatial layout, ornaments and materials.",
    }[kind]
    for index, name in enumerate(name for name in view_names if name != "front"):
        perspective = perspectives[name]
        workflow = qwen_character_view_workflow(
            f"<image1> Produce a strict {perspective} turntable reference of this same game asset. "
            f"Preserve every recognizable feature of the source asset. {prompt}. {geometry} "
            "Rotate the camera around the original object by the corresponding turntable angle. "
            "Maintain constant camera distance, a fixed elevation and the original framing. "
            "Maintain exact 3D shape, scale, construction, parts, surfaces and colors across all views. "
            "Centered entire object, complete silhouette, bright white studio background. "
            "Single camera view, no perspective foreshortening, no labels and no additional objects.",
            uploaded, seed + index,
        )
        images = submit_and_download(
            endpoint, workflow, "8", output, 1, "qwen", gpu_index,
            timeout_seconds=settings.timeout_seconds,
        )
        target = output / f"{name}.png"
        images[0].rename(target)
        saved.append(target)
    front = output / "front.png"
    shutil.copy2(source, front)
    saved.insert(0, front)
    log.write(f"Qwen multi-view references saved: {[str(path) for path in saved]}\n")
    log.flush()
    return saved
