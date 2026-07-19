def test_reasoning_benchmarks_requires_login(client):
    response = client.get("/api/reasoning-benchmarks")

    assert response.status_code == 401


def test_reasoning_benchmarks_returns_seeded_catalog(client, auth_headers):
    response = client.get("/api/reasoning-benchmarks", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"]
    assert payload["last_updated_at"]
    assert len(payload["harnesses"]) == 2
    assert len(payload["models"]) == 5
    assert len(payload["tests"]) == 1

    test = payload["tests"][0]
    assert test["id"] == "test-planning-2026-07"
    assert test["category"] == "planning"
    assert len(test["criteria"]) == 11
    assert len(test["entries"]) == 5
    assert all(len(entry["scores"]) == 11 for entry in test["entries"])
    assert test["findings"]
    assert test["limitations"]

    harness_ids = {harness["id"] for harness in payload["harnesses"]}
    assert all(entry["harness_id"] in harness_ids for entry in test["entries"])
