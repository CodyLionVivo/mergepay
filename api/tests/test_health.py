from fastapi.testclient import TestClient


def test_root_returns_api_name(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"name": "MergePay API", "status": "ok"}


def test_health_returns_healthy(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
