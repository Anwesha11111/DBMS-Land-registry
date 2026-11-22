# tests/test_12_sql_console.py
import pytest
from backend.app import create_app
from backend.db.mock_store import mock_db

@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client

def test_get_challenges(client):
    res = client.get("/api/sql/challenges")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["challenges"]) >= 6
    assert "plot" in data["schemas"]
    assert "registry_entry" in data["schemas"]

def test_execute_query_validation(client):
    # Empty query
    res = client.post("/api/sql/execute", json={"query": ""})
    assert res.status_code == 400

    # Destructive command blocked
    res = client.post("/api/sql/execute", json={"query": "DROP DATABASE land_registry;"})
    assert res.status_code == 403

def test_execute_select_query_mock_and_live(client):
    # Seed a sample plot in mock store if in mock mode
    mock_db.plots["test_sql_p1"] = {
        "plot_id": "test_sql_p1",
        "street_address": "123 MG Road",
        "city": "Bengaluru",
        "area_sqft": 10500.0,
        "length_m": 35.0,
        "width_m": 30.0,
        "boundary": "POLYGON((...))"
    }
    mock_db.registry["reg_test_sql_p1"] = {
        "registry_id": "reg_test_sql_p1",
        "plot_id": "test_sql_p1",
        "current_owner_id": "own_alice",
        "legal_status": "Clear",
        "last_block_height": 1,
        "last_block_hash": "00000000"
    }

    # Query plots with area > 8000
    query = "SELECT plot_id, street_address, area_sqft FROM plot WHERE area_sqft > 8000 ORDER BY area_sqft DESC;"
    res = client.post("/api/sql/execute", json={"query": query})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "columns" in data
    assert "rows" in data
    assert data["row_count"] >= 1
    assert "execution_time_ms" in data
