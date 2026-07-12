def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_me_requires_auth(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401
