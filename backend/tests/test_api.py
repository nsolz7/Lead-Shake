from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


def test_api_requires_local_login_and_reports_source_health(db):
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            assert client.get("/api/dashboard").status_code == 401
            response = client.post("/api/auth/login", json={"username": "admin", "password": "change-me-now"})
            assert response.status_code == 200
            token = response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            health = client.get("/api/sources/health", headers=headers)
            assert health.status_code == 200
            assert any(source["id"] == "nc_sos_subscription" for source in health.json())
            assert client.get("/api/leads", headers=headers).json()["items"] == []
            readiness = client.get("/api/model-readiness", headers=headers).json()
            assert readiness["ready_for_time_split_evaluation"] is False
            paid = client.post("/api/runs", headers=headers, json={"source_id": "email_verifier"})
            assert paid.status_code == 400
            run = client.post("/api/runs", headers=headers, json={"source_id": "sc_sos"})
            assert run.status_code == 202 and run.json()["status"] == "awaiting_manual"
            disabled = client.patch("/api/sources/overture_places?enabled=false", headers=headers)
            assert disabled.status_code == 200
            blocked = client.post("/api/runs", headers=headers, json={"source_id": "overture_places"})
            assert blocked.status_code == 404
    finally:
        app.dependency_overrides.clear()
