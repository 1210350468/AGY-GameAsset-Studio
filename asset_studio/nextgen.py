from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image


MIN_GPU1_FREE_MIB = 50000
ANIMA_MODEL = "Anima-2.9B-preview-v1.safetensors"
ANIMA_TEXT_ENCODER = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"
QWEN_MODEL = "qwen_image_2.1_bf16.safetensors"
QWEN_TEXT_ENCODER = "qwen3vl_8b_bf16.safetensors"
QWEN_VAE = "qwen_image_2.1_vae_bf16.safetensors"


def require_gpu1_headroom() -> int:
    result = subprocess.check_output(
        ["nvidia-smi", "--id=1", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        text=True,
    )
    available_mib = int(result.strip())
    if available_mib < MIN_GPU1_FREE_MIB:
        raise RuntimeError(
            f"GPU1 空闲显存 {available_mib} MiB，实际推理要求至少 {MIN_GPU1_FREE_MIB} MiB"
        )
    return available_mib


def anima_candidates_workflow(prompt: str, seed: int, count: int = 4) -> dict:
    if count < 1 or count > 8:
        raise ValueError("Anima 候选数量必须在 1 至 8 之间")
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ANIMA_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA_TEXT_ENCODER, "type": "stable_diffusion"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0],
            "text": "worst quality, blurry, cropped, duplicate character, multiple views, fused limbs, cut off feet, noisy background",
        }},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": count}},
        "7": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 35, "cfg": 4.0,
            "sampler_name": "euler", "scheduler": "sgm_uniform", "denoise": 1.0,
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0],
        }},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "agy_nextgen/anima_candidates"}},
    }


def qwen_character_view_workflow(prompt: str, reference_filename: str, seed: int) -> dict:
    if not reference_filename:
        raise ValueError("必须提供真实原画文件")
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_TEXT_ENCODER, "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": reference_filename}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "negative_prompt": "", "resolution": 1024,
            "images.image_1": ["4", 0],
        }},
        "6": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 25, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
            "model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1],
            "latent_image": ["5", 2],
        }},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "agy_nextgen/qwen_reference_view"}},
    }


def get_object_info(endpoint: str) -> dict:
    with httpx.Client(base_url=endpoint, timeout=45) as client:
        response = client.get("/object_info")
        response.raise_for_status()
        return response.json()


def validate_installed_nodes(endpoint: str, model: str) -> dict:
    info = get_object_info(endpoint)
    if model == "anima":
        required_types = ["CLIPLoader", "CLIPTextEncode", "EmptyLatentImage", "KSampler", "SaveImage", "UNETLoader", "VAEDecode", "VAELoader"]
        filenames = {
            "UNETLoader": ANIMA_MODEL,
            "CLIPLoader": ANIMA_TEXT_ENCODER,
            "VAELoader": ANIMA_VAE,
        }
    elif model == "qwen":
        required_types = ["CLIPLoader", "KSampler", "LoadImage", "SaveImage", "TextEncodeQwenImage21", "UNETLoader", "VAEDecode", "VAELoader"]
        filenames = {
            "UNETLoader": QWEN_MODEL,
            "CLIPLoader": QWEN_TEXT_ENCODER,
            "VAELoader": QWEN_VAE,
        }
    else:
        raise ValueError(f"未知模型：{model}")
    missing_nodes = [node for node in required_types if node not in info]
    if missing_nodes:
        raise RuntimeError(f"ComfyUI 缺少真实节点：{missing_nodes}")

    loader_names = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name"}
    for node_type, selected in filenames.items():
        key = loader_names[node_type]
        options = info[node_type]["input"]["required"][key][0]
        if selected not in options:
            raise FileNotFoundError(f"ComfyUI 模型文件尚未安装：{selected}")

    return {"model": model, "verified_nodes": required_types, "installed_model_files": True}


def submit_and_download(
    endpoint: str, workflow: dict, output_node: str, destination: Path,
    expected_images: int, timeout_seconds: int = 1800,
) -> list[Path]:
    require_gpu1_headroom()
    destination.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=endpoint, timeout=120) as client:
        submitted = client.post("/prompt", json={"prompt": workflow})
        submitted.raise_for_status()
        payload = submitted.json()
        prompt_id = payload["prompt_id"]
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history_response = client.get(f"/history/{prompt_id}")
            history_response.raise_for_status()
            result = history_response.json().get(prompt_id)
            if result:
                status = result.get("status", {})
                if status.get("status_str") != "success":
                    raise RuntimeError(f"ComfyUI 实际推理未成功：{status}")
                images = result["outputs"][output_node]["images"]
                if len(images) != expected_images:
                    raise RuntimeError(f"图片数量错误，预期 {expected_images}，实际 {len(images)}")
                saved = []
                for index, info in enumerate(images):
                    image_response = client.get("/view", params={
                        "filename": info["filename"],
                        "subfolder": info.get("subfolder", ""),
                        "type": info.get("type", "output"),
                    })
                    image_response.raise_for_status()
                    filename = destination / f"{prompt_id}_{index + 1}.png"
                    filename.write_bytes(image_response.content)
                    with Image.open(filename) as image:
                        image.verify()
                    saved.append(filename)
                cleanup = client.post("/free", json={"unload_models": True, "free_memory": True})
                cleanup.raise_for_status()
                return saved
            time.sleep(2)
        raise TimeoutError(f"真实推理超时：{prompt_id}")


def upload_reference(endpoint: str, reference: Path) -> str:
    with httpx.Client(base_url=endpoint, timeout=120) as client:
        with reference.open("rb") as image:
            response = client.post("/upload/image", files={"image": (reference.name, image, "image/png")})
        response.raise_for_status()
        return response.json()["name"]
