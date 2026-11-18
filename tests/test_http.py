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
        assert client.get("/api/assets").json() == {"assets": []}
        assert client.get("/nextgen").status_code == 200
        assert client.get("/api/nextgen/previews").status_code == 200
        assert client.get("/api/nextgen/images/anima/missing.png").status_code == 404


def test_missing_job_returns_404() -> None:
    with TestClient(app) as client:
        assert client.get("/api/jobs/not-a-valid-uuid").status_code == 404
        assert client.get("/api/jobs/00000000000000000000000000000000/log").status_code == 404
        assert client.get("/api/jobs/00000000000000000000000000000000/file/model.glb").status_code == 404

