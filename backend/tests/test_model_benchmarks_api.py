def test_model_benchmarks_requires_login(client):
    response = client.get("/api/model-benchmarks")

    assert response.status_code == 401


def test_model_benchmarks_returns_normalized_global_catalog(client, auth_headers):
    response = client.get("/api/model-benchmarks", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"]
    assert payload["last_verified_at"]
    assert len(payload["providers"]) == 10
    assert len(payload["models"]) == 30
    assert payload["benchmarks"]
    assert payload["scores"]
    assert all(model["display_name"] for model in payload["models"])
    assert all(score["source"]["url"].startswith("https://") for score in payload["scores"])
