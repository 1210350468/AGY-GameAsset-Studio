import argparse
import io
import json
import zipfile

import httpx


parser = argparse.ArgumentParser(description="使用真实 API 和资源文件验收已完成资产")
parser.add_argument("--base-url", default="http://127.0.0.1:18333")
parser.add_argument("--job-id", required=True)
parser.add_argument("--compare-job-id")
arguments = parser.parse_args()

with httpx.Client(base_url=arguments.base_url, timeout=90) as client:
    response = client.get(f"/api/jobs/{arguments.job_id}")
    response.raise_for_status()
    job = response.json()
    assert job["status"] == "completed", f"任务尚未完成：{job['status']}"

    response = client.get(f"/api/jobs/{arguments.job_id}/inspect")
    response.raise_for_status()
    quality = response.json()
    assert quality["faces"] > 0

    response = client.get(f"/api/jobs/{arguments.job_id}/file/godot_asset.zip")
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None, "ZIP 文件校验失败"
        required = {"model.glb", "manifest.json", "quality.json", "game_asset.tscn"}
        assert required.issubset(archive.namelist()), "资源包缺少 Godot 文件"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["asset_id"] == arguments.job_id
        assert bool(manifest["rig_generated"]) == bool(quality["skinned"])
        scene = archive.read("game_asset.tscn").decode("utf-8")
        assert "CollisionShape3D" in scene
        assert "model.glb" in scene
        if manifest["rig_generated"]:
            assert quality["joints"] > 0

    old_boundary = None
    if arguments.compare_job_id:
        previous = client.get(f"/api/jobs/{arguments.compare_job_id}/inspect")
        previous.raise_for_status()
        old_boundary = previous.json()["boundary_edge_ratio"]
        assert quality["boundary_edge_ratio"] < old_boundary, "优化后的开放边界比例未降低"

print(json.dumps({
    "asset_id": arguments.job_id,
    "title": job["title"],
    "status": job["status"],
    "faces": quality["faces"],
    "boundary_edge_ratio": quality["boundary_edge_ratio"],
    "previous_boundary_edge_ratio": old_boundary,
    "joints": quality["joints"],
    "textures": quality["images"],
    "review_required": quality["review_required"],
    "godot_zip_bytes": len(response.content),
}, ensure_ascii=False, indent=2))
