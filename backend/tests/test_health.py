"""Smoke tests for the scaffold. Domain tests land in Prompt 2."""


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "purchasing-agent"


def test_scenarios_catalogue(client) -> None:
    response = client.get("/scenarios")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {
        "recommendation-review",
        "supplier-shortfall",
        "demand-change",
        "constrained-buy",
    }
