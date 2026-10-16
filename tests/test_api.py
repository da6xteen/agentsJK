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

def test_api_complex_explanation_and_actions():
    # 1. Get complex explanation
    response = client.get("/api/complexes/c-001/explanation")
    assert response.status_code == 200
    data = response.json()
    assert data["complex_id"] == "c-001"
    assert "explanation" in data
    assert "permits_table" in data
    assert "disclaimer" in data

    # 2. Confirm complex review
    conf_res = client.post("/api/complexes/c-001/confirm", json={"author": "Аналитик МИО", "note": "Проверено"})
    assert conf_res.status_code == 200
    assert conf_res.json()["review_status"] == "confirmed"

    # 3. Return complex review
    ret_res = client.post("/api/complexes/c-001/return", json={"author": "Аналитик МИО", "note": "Нужно доп. сведение"})
    assert ret_res.status_code == 200
    assert ret_res.json()["review_status"] == "returned"

    # 4. Print report
    print_res = client.get("/api/complexes/c-001/print")
    assert print_res.status_code == 200
    assert "SAQ QURYLYS" in print_res.text
    assert "Оценка риска — не юридическое заключение." in print_res.text
