import base64
import io
import os
import shutil
from pathlib import Path

import httpx
from PIL import Image

from asset_studio.comfy import generate_image
from asset_studio.concept_quality import select_concept_candidate
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
        f"Create one detailed Chinese wuxia/xianxia seasonal action RPG game asset reference. {prompt}. "
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
                descriptions = {
                    "character": (
                        "Single adult Chinese wuxia/xianxia martial artist in neutral symmetric A-pose, "
                        "complete head-to-toe anatomy, separated arms, visible fingers, two separated boots, "
                        "wearable garments with individually understandable collars, belts, sleeves, fasteners "
                        "and detachable armor. Leave any weapon to a separate asset. "
                    ),
                    "monster": (
                        "A coherent Chinese mythological enemy creature with fully visible head, torso, limbs "
                        "and articulated joints, physically plausible feet, all claws and tail attachments "
                        "separated, balanced neutral pose, no ground plane, no smoke or floating effects. "
                    ),
                    "weapon": (
                        "One complete traditional Chinese weapon, physically plausible blade and handle assembly, "
                        "full-length isolated product reference, consistent scale and materials. "
                    ),
                    "equipment": (
                        "One detached piece of Chinese martial armor or garment, clear fastening and lining, "
                        "orthographic product reference, physically plausible thickness and materials. "
                    ),
                    "prop": (
                        "One isolated handcrafted Chinese historical fantasy game prop, clear construction "
                        "and mechanically plausible distinct parts. "
                    ),
                    "scene": (
                        "One standalone modular Chinese historical environment component with real architectural "
                        "construction, clear openings and connections, no surrounding terrain or combined scenery. "
                    ),
                }
                workflow = qwen_concept_workflow(
                    "Original high-fidelity Chinese wuxia/xianxia seasonal action RPG modeling reference. "
                    + descriptions[kind]
                    + f"Design details: {prompt}. "
                    + "Full visible subject, centered orthographic frontal studio angle, even daylight, "
                    + "subtle realistic PBR materials, restrained jade-green, ink-blue and warm gold palette, "
                    + "uniform pure white background, no floor, no shadow baked into geometry, "
                    + "no ornate presentation border, no typography, no dramatic perspective.",
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
    selected = select_concept_candidate(
        saved, destination.parent / "concept_quality.json",
        animated=kind in {"character", "monster"},
    )
    shutil.copy2(selected, destination)
    log.write(f"Selected source image {selected.name} / {len(saved)} by real foreground and framing checks: {destination}\n")
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
    perspectives = {"right": ("90 degrees clockwise", "right profile"), "back": ("180 degrees", "back view"), "left": ("270 degrees clockwise", "left profile")}
    geometry = {
        "character": "Keep the exact neutral pose, body proportions, clothing layers, boots, hands, weapons, attachments and anatomy.",
        "monster": "Keep the exact anatomy, stance, number of limbs, appendages, head shape, armor and tail attachments.",
        "weapon": "Keep the exact blade, grip, guard, handle, pommel, material layers, ornament positions and physical proportions.",
        "equipment": "Keep the exact armor structure, straps, buckles, fasteners, layered materials and mounting points.",
        "prop": "Keep the exact assembly, silhouette, mechanical construction, carved details, material colors and physical proportions.",
        "scene": "Keep the exact architectural structure, entrances, floor boundaries, spatial layout, ornaments and materials.",
    }[kind]
    for index, name in enumerate(name for name in view_names if name != "front"):
        target = output / f"{name}.png"
        if target.is_file():
            with Image.open(target) as existing:
                existing.verify()
            saved.append(target)
            log.write(f"Reusing already completed QImage {name} source image: {target}\n")
            continue
        angle, perspective = perspectives[name]
        workflow = qwen_character_view_workflow(
            f"<image1> Generate the {perspective} at exactly {angle} from the canonical front view "
            "of the identical Chinese wuxia/xianxia game asset shown in image 1. "
            "Treat image 1 as the immutable character design sheet, preserve identity, original anatomy, "
            "hair shape and exact clothing layers, attached objects, material colors and patterns. "
            f"{geometry} Original design instructions: {prompt}. "
            "Fixed eye-level turntable camera, same vertical framing and character scale, neutral A-pose, "
            "same studio lighting. Back view must show the actual back construction rather than a painted "
            "version of the front. Side view must show true thickness and fully visible silhouette. "
            "One full isolated body centered on pure white with no floor or cast shadow. "
            "No extra arms, mirrored accessories, invented weapons, scenery, text, collage or perspective shift.",
            uploaded, seed + index,
        )
        images = submit_and_download(
            endpoint, workflow, "8", output, 1, "qwen", gpu_index,
            timeout_seconds=settings.timeout_seconds,
        )
        images[0].rename(target)
        saved.append(target)
    front = output / "front.png"
    shutil.copy2(source, front)
    saved.insert(0, front)
    log.write(f"Qwen multi-view references saved: {[str(path) for path in saved]}\n")
    log.flush()
    return saved
