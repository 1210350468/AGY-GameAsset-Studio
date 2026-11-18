import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image


def image_workflow(*, prompt: str, checkpoint: str, seed: int, steps: int, width: int, height: int, kind: str = "character") -> dict[str, Any]:
    subject_guidance = {
        "character": "one full body humanoid character, standing neutral A pose, arms separated from torso, entire legs and feet visible, camera facing front,",
        "monster": "one full body monster, neutral standing pose, arms and legs separated, entire creature visible, camera facing front,",
        "weapon": "one single weapon item, isolated upright, no person or hand holding it,",
        "equipment": "one single fantasy equipment set, all armor pieces readable, isolated object,",
        "prop": "one single game environment prop, isolated three-quarter view,",
        "scene": "one isolated modular environment asset, three-quarter front view,",
    }[kind]
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"batch_size": 1, "width": width, "height": height}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "masterpiece, best quality, high detail, dark fantasy game asset concept art, "+prompt+
                ", " + subject_guidance + " centered composition, clean isolated silhouette, single subject, "
                "white studio background, soft even diffuse illumination, no cast shadow, entire object visible",
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "low quality, cropped, cut off, multiple subjects, duplicate silhouette, duplicate figure, "
                "reference sheet, turnaround sheet, lineup, side drawing, inset shadow figure, cast shadow, "
                "dark shadow, text, watermark, logo, background scenery, motion blur, overlapping limbs",
            },
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": 5.5,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "agy_asset_studio"},
        },
    }


def generate_image(
    *, base_url: str, checkpoint: str, prompt: str, destination: Path, kind: str = "character",
    seed: int, steps: int, timeout_seconds: int, log,
) -> None:
    workflow = image_workflow(
        prompt=prompt, checkpoint=checkpoint, seed=seed, steps=steps, width=1024, height=1024, kind=kind,
    )
    with httpx.Client(base_url=base_url, timeout=30) as client:
        submitted = client.post("/prompt", json={"prompt": workflow})
        submitted.raise_for_status()
        response = submitted.json()
        if "prompt_id" not in response:
            raise RuntimeError(f"ComfyUI 未接受任务：{response}")
        prompt_id = response["prompt_id"]
        log.write(f"ComfyUI prompt_id={prompt_id}\n")
        log.flush()

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = client.get(f"/history/{prompt_id}")
            history.raise_for_status()
            result = history.json().get(prompt_id)
            if result:
                status = result.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI 推理失败：{status}")
                images = result.get("outputs", {}).get("9", {}).get("images", [])
                if len(images) != 1:
                    raise RuntimeError(f"ComfyUI 返回的图片数量异常：{len(images)}")
                info = images[0]
                download = client.get(
                    "/view",
                    params={"filename": info["filename"], "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")},
                )
                download.raise_for_status()
                destination.write_bytes(download.content)
                with Image.open(destination) as rendered:
                    rendered.verify()
                freed = client.post("/free", json={"unload_models": True, "free_memory": True})
                freed.raise_for_status()
                log.write(f"ComfyUI concept saved: {destination}\n")
                log.flush()
                return
            time.sleep(2)
    raise TimeoutError(f"ComfyUI 生成超过 {timeout_seconds} 秒：{prompt_id}")

