import argparse
import json
from pathlib import Path
from PIL import Image

from asset_studio.nextgen import (
    anima_candidates_workflow,
    qwen_character_view_workflow,
    require_gpu_headroom,
    submit_and_download,
    upload_reference,
    validate_installed_nodes,
)


parser = argparse.ArgumentParser(description="AGY 游戏角色原画候选与一致性视角实测")
parser.add_argument("--endpoint")
parser.add_argument("--model", choices=["anima", "qwen"], required=True)
parser.add_argument("--validate", action="store_true", help="使用真实 ComfyUI 节点清单验证权重和节点")
parser.add_argument("--reference", type=Path, help="Qwen 同角色多视角使用的实际 PNG 原画")
parser.add_argument("--output", type=Path, default=Path("data/nextgen-experiments"))
parser.add_argument("--seed", type=int, default=20261118)
args = parser.parse_args()

gpu_file = Path("/data/xmu/ym/asset-studio-data") / f"nextgen-{args.model}-gpu"
endpoint = args.endpoint or f"http://127.0.0.1:{8189 if args.model == 'anima' else 8190}"

if args.validate:
    print(json.dumps(validate_installed_nodes(endpoint, args.model), ensure_ascii=False, indent=2))
else:
    gpu_index = int(gpu_file.read_text(encoding="utf-8").strip())
    available = require_gpu_headroom(args.model, gpu_index)
    print(f"GPU{gpu_index} 推理前确认空闲显存：{available} MiB")
    validate_installed_nodes(endpoint, args.model)

    if args.model == "anima":
        prompt = (
            "1boy, solo, full body, standing neutral A-pose, arms separated from torso, "
            "original dark fantasy exile warrior, worn iron plate armor, leather straps, "
            "one large horn on right shoulder, broad shoulders, muted crimson cape, "
            "heavy medieval boots, intricate steel engravings, polished professional fantasy game concept art, "
            "entire character visible, clear front view, simple pure white studio background, "
            "soft diffuse lighting, 2026"
        )
        workflow = anima_candidates_workflow(prompt, args.seed, count=4)
        files = submit_and_download(endpoint, workflow, "9", args.output / "anima", expected_images=4, model=args.model, gpu_index=gpu_index)
        print(json.dumps({"anima_candidates": [str(path) for path in files]}, ensure_ascii=False, indent=2))
    else:
        reference = args.reference.resolve(strict=True)
        if reference.suffix.lower() != ".png":
            raise ValueError("参考原画必须为 PNG 文件")
        uploaded_name = upload_reference(endpoint, reference)
        results = {}
        for index, (name, description) in enumerate((
            ("front", "front orthographic view"),
            ("left", "left side orthographic view"),
            ("back", "back orthographic view"),
            ("right", "right side orthographic view"),
        )):
            view_dir = args.output / "qwen" / name
            existing = sorted(view_dir.glob("*.png")) if view_dir.is_dir() else []
            if existing:
                if len(existing) != 1:
                    raise RuntimeError(f"{name} 已存在多个真实生成文件：{existing}")
                with Image.open(existing[0]) as image:
                    image.verify()
                results[name] = str(existing[0])
                continue
            prompt = (
                f"<image1> Draw exactly the same original dark fantasy character from the {description}. "
                "Preserve the character identity, outfit design, horns, armor topology, colors, fabric, and proportions. "
                "One full body character, symmetrical neutral A-pose, entire feet visible, isolated white studio background. "
                "One viewpoint only, no composite reference sheet, no labels."
            )
            workflow = qwen_character_view_workflow(prompt, uploaded_name, args.seed + index)
            files = submit_and_download(endpoint, workflow, "8", view_dir, expected_images=1, model=args.model, gpu_index=gpu_index)
            results[name] = str(files[0])
        print(json.dumps({"qwen_views": results}, ensure_ascii=False, indent=2))
