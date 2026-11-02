# tests/test_01_health.py
def test_health_endpoint(client):
    """Prompt 1: Tests /health endpoint returns healthy status for both databases."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"
    assert "postgres" in data["databases"]
    assert "mongo" in data["databases"]
    assert data["databases"]["postgres"]["status"] == "healthy"
    assert data["databases"]["mongo"]["status"] == "healthy"
