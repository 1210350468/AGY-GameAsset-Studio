import argparse
import json
from pathlib import Path

from asset_studio.nextgen import (
    anima_candidates_workflow,
    qwen_character_view_workflow,
    require_gpu1_headroom,
    submit_and_download,
    upload_reference,
    validate_installed_nodes,
)


parser = argparse.ArgumentParser(description="AGY 游戏角色原画候选与一致性视角实测")
parser.add_argument("--endpoint", default="http://127.0.0.1:8189")
parser.add_argument("--model", choices=["anima", "qwen"], required=True)
parser.add_argument("--validate", action="store_true", help="使用真实 ComfyUI 节点清单验证权重和节点")
parser.add_argument("--reference", type=Path, help="Qwen 同角色多视角使用的实际 PNG 原画")
parser.add_argument("--output", type=Path, default=Path("data/nextgen-experiments"))
parser.add_argument("--seed", type=int, default=20261118)
args = parser.parse_args()

if args.validate:
    print(json.dumps(validate_installed_nodes(args.endpoint, args.model), ensure_ascii=False, indent=2))
else:
    available = require_gpu1_headroom()
    print(f"GPU1 推理前确认空闲显存：{available} MiB")
    validate_installed_nodes(args.endpoint, args.model)

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
        files = submit_and_download(args.endpoint, workflow, "9", args.output / "anima", expected_images=4)
        print(json.dumps({"anima_candidates": [str(path) for path in files]}, ensure_ascii=False, indent=2))
    else:
        reference = args.reference.resolve(strict=True)
        if reference.suffix.lower() != ".png":
            raise ValueError("参考原画必须为 PNG 文件")
        uploaded_name = upload_reference(args.endpoint, reference)
        results = {}
        for index, (name, description) in enumerate((
            ("front", "front orthographic view"),
            ("left", "left side orthographic view"),
            ("back", "back orthographic view"),
            ("right", "right side orthographic view"),
        )):
            prompt = (
                f"<image1> Draw exactly the same original dark fantasy character from the {description}. "
                "Preserve the character identity, outfit design, horns, armor topology, colors, fabric, and proportions. "
                "One full body character, symmetrical neutral A-pose, entire feet visible, isolated white studio background. "
                "One viewpoint only, no composite reference sheet, no labels."
            )
            workflow = qwen_character_view_workflow(prompt, uploaded_name, args.seed + index)
            files = submit_and_download(args.endpoint, workflow, "8", args.output / "qwen" / name, expected_images=1)
            results[name] = str(files[0])
        print(json.dumps({"qwen_views": results}, ensure_ascii=False, indent=2))
