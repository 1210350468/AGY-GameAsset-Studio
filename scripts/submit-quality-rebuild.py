import json

import httpx


payload = {
    "title": "流亡战士 · 高保真姿态重建",
    "kind": "character",
    "mode": "whole",
    "prompt": (
        "Original dark fantasy exile knight, blackened steel armor, crimson cloak, "
        "heavy Gothic helmet with one curved horn, articulated shoulder plates, leather belts, "
        "believable human anatomy, hands fully visible, both legs standing clearly apart, "
        "entire silhouette from helmet to boots in a relaxed neutral A-pose, "
        "cape attached to shoulders and hanging freely behind the legs, "
        "all armor shapes cleanly separated, intricate but physically plausible materials, "
        "one full body character on a clean white orthographic studio background"
    ),
    "image_model": "qwen",
    "image_count": "1",
    "image_steps": "30",
    "multi_views": "true",
    "multi_view_strategy": "front-back",
    "pixal_low_vram": "false",
    "rig": "false",
    "target_faces": "250000",
    "seed": "20261119",
}

with httpx.Client(timeout=45) as client:
    response = client.post("http://127.0.0.1:18333/api/jobs", data=payload)
    response.raise_for_status()
    job = response.json()
    status = client.get(f"http://127.0.0.1:18333/api/jobs/{job['job_id']}")
    status.raise_for_status()

print(json.dumps({"submission": job, "job": status.json()}, ensure_ascii=False))
