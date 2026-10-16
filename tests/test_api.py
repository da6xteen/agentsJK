import os
import pytest
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def setup_tmp_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_saq.db")
    monkeypatch.setenv("DB_PATH", db_file)
    import database.repository
    database.repository.repo = database.repository.AdRepository(db_path=db_file)
    import app.main
    app.main.repo = database.repository.repo

from app.main import app

client = TestClient(app)

def test_api_collector_run_demo():
    response = client.post("/api/collector/run", json={
        "source": "demo",
        "query_or_url": ""
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] >= 12

def test_api_get_ads():
    # Run collector first to ensure db is populated
    client.post("/api/collector/run", json={"source": "demo", "query_or_url": ""})
    response = client.get("/api/ads")
    assert response.status_code == 200
    ads = response.json()
    assert isinstance(ads, list)
    assert len(ads) > 0

def test_api_create_manual_ad():
    response = client.post(
        "/api/ads",
        data={
            "platform": "manual",
            "account": "Тестовый Аналитик",
            "url": "https://test.local/ad1",
            "text": "Продажа квартиры в строящемся ЖК Тест",
            "is_demo": "true"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "manual"
    assert data["account"] == "Тестовый Аналитик"
    assert data["status"] == "new"
