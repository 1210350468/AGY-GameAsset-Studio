import json
import zipfile
from pathlib import Path

import trimesh

from asset_studio.comfy import image_workflow
from asset_studio.pipeline import AssetPipeline
from asset_studio.settings import Settings
from asset_studio.store import Store


def test_comfy_workflow_is_complete() -> None:
    workflow = image_workflow(
        prompt="冰霜骑士，蓝色铠甲", checkpoint="waiIllustriousSDXL_v170.safetensors",
        seed=31415, steps=32, width=1024, height=1024,
    )
    assert workflow["4"]["inputs"]["ckpt_name"] == "waiIllustriousSDXL_v170.safetensors"
    assert workflow["3"]["inputs"]["seed"] == 31415
    assert "冰霜骑士" in workflow["6"]["inputs"]["text"]
    assert workflow["9"]["inputs"]["images"] == ["8", 0]
    for node in workflow.values():
        for argument in node["inputs"].values():
            if isinstance(argument, list) and len(argument) == 2 and isinstance(argument[0], str):
                assert argument[0] in workflow


def test_database_persists_status_and_restart(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.sqlite3")
    store.create("job123", "法杖", "weapon", "whole", {"rig": False})
    assert store.get("job123")["status"] == "queued"
    store.update("job123", status="running", stage="Pixal3D", progress=0.4)
    assert Store(tmp_path / "jobs.sqlite3").get("job123")["progress"] == 0.4
    store.recover_interrupted()
    assert store.get("job123")["status"] == "failed"
    assert store.get("job123")["stage"] == "interrupted"


def test_real_geometry_package_and_archive(tmp_path: Path) -> None:
    # 使用 trimesh 正式导出的 GLB 验证几何读取、资源清单和 Godot 打包。
    settings = Settings(
        root=Path(__file__).resolve().parents[1], data_root=tmp_path,
        comfy_url="http://127.0.0.1:8188",
        checkpoint="waiIllustriousSDXL_v170.safetensors",
        pixal_low_vram=True, blender="blender", timeout_seconds=20,
    )
    pipeline = AssetPipeline(settings)
    model = trimesh.creation.icosphere(subdivisions=2, radius=1.1)
    job_id = "8f0211592a1d47e997750100292e9309"
    path = settings.jobs_root / job_id
    path.mkdir()
    glb_file = path / "model.glb"
    model.export(glb_file)
    real_job = {
        "id": job_id, "title": "球形几何测试资产", "kind": "prop", "mode": "import",
        "created_at": "2026-11-17T00:00:00Z", "params": {"rig": False},
    }
    pipeline._package(real_job, path, glb_file)
    quality = json.loads((path / "quality.json").read_text(encoding="utf-8"))
    assert quality["faces"] == len(model.faces)
    assert quality["geometry_count"] == 1
    assert quality["bounds"][0][0] < 0 < quality["bounds"][1][0]
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["animations_included"] is False
    with zipfile.ZipFile(path / "godot_asset.zip") as archive:
        assert set(archive.namelist()) == {"model.glb", "manifest.json", "quality.json"}
        assert archive.read("model.glb") == glb_file.read_bytes()


def test_rigged_requirement_checks_real_skin(tmp_path: Path) -> None:
    settings = Settings(
        root=Path(__file__).resolve().parents[1], data_root=tmp_path,
        comfy_url="http://127.0.0.1:8188", checkpoint="test.safetensors",
        pixal_low_vram=True, blender="blender", timeout_seconds=20,
    )
    pipeline = AssetPipeline(settings)
    job_id = "9f0211592a1d47e997750100292e9309"
    path = settings.jobs_root / job_id
    path.mkdir()
    glb_file = path / "model.glb"
    trimesh.creation.box().export(glb_file)
    import pytest

    with pytest.raises(ValueError, match="缺少 skin"):
        pipeline._package(
            {"id": job_id, "title": "角色骨骼验证", "kind": "character", "mode": "whole",
             "created_at": "2026-11-17T00:00:00Z", "params": {"rig": True}},
            path, glb_file,
        )

