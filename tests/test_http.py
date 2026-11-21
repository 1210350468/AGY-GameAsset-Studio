from fastapi.testclient import TestClient

from asset_studio.api import app


def test_real_http_routes() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "agy-game-asset-studio"
        assert client.get("/").status_code == 200
        assert "AGY 资产工坊" in client.get("/").text
        assert client.get("/style.css").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/app.bundle.js").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/api/system").status_code == 200
        assert "cuda" in client.get("/api/system").json()
        assert client.get("/api/config").status_code == 200
        models = client.get("/api/config").json()["image_models"]
        assert {model["id"] for model in models} == {"qwen", "anima", "wai", "gpt-image"}
        assert isinstance(client.get("/api/config").json()["pixal_multiview_ready"], bool)
        assert client.get("/api/assets").json() == {"assets": []}
        assert client.get("/nextgen").status_code == 200
        assert client.get("/api/nextgen/previews").status_code == 200
        assert client.get("/api/nextgen/images/anima/missing.png").status_code == 404
        assert len(client.get("/api/nextgen/experiments").json()["experiments"]) == 3
        assert client.get("/api/nextgen/experiments/invalid/model.glb").status_code == 404
        assert client.post("/api/nextgen/experiments/invalid/package").status_code == 404


def test_missing_job_returns_404() -> None:
    with TestClient(app) as client:
        assert client.get("/api/jobs/not-a-valid-uuid").status_code == 404
        assert client.get("/api/jobs/00000000000000000000000000000000/log").status_code == 404
        assert client.get("/api/jobs/00000000000000000000000000000000/file/model.glb").status_code == 404
        assert client.get("/api/jobs/00000000000000000000000000000000/file/preview.glb").status_code == 404
        assert client.post("/api/jobs/00000000000000000000000000000000/repair-texture").status_code == 404
        assert client.post("/api/jobs/00000000000000000000000000000000/rebuild-multiview").status_code == 404
        assert client.post("/api/jobs/00000000000000000000000000000000/repair-ground").status_code == 404
        assert client.post("/api/jobs/00000000000000000000000000000000/repair-ground-mesh").status_code == 404


def test_image_selector_validates_input() -> None:
    with TestClient(app) as client:
        invalid = client.post("/api/jobs", data={"title": "测试模型", "image_model": "other"})
        assert invalid.status_code == 400
        count = client.post("/api/jobs", data={"title": "测试模型", "image_count": "3"})
        assert count.status_code == 400
        mode = client.post("/api/jobs", data={"title": "测试模型", "multi_views": "true", "mode": "parts"})
        assert mode.status_code == 400
        invalid_strategy = client.post("/api/jobs", data={"title": "测试模型", "multi_view_strategy": "left-only"})
        assert invalid_strategy.status_code == 400

