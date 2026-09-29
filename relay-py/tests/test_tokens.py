import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.tokens import PREFIX, TokenError, TokenStore


def make(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_username="mogie", admin_password="secret")
    client = TestClient(create_app(settings))
    assert client.post("/api/login", json={"username": "mogie", "password": "secret"}).status_code == 200
    return client


# ----- the store -----

def test_create_and_verify(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, rec = store.create("Claude", "read", now=1000)
    assert token.startswith(PREFIX)
    got = store.verify(token, now=1001)
    assert got is not None and got.name == "Claude" and got.scope == "read"


def test_only_a_hash_is_stored(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, _ = store.create("Claude")
    raw = (tmp_path / "t.db").read_bytes()
    assert token.encode() not in raw


def test_wrong_and_junk_tokens_fail(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    store.create("Claude")
    assert store.verify("fgat_nope") is None
    assert store.verify("junk") is None
    assert store.verify("") is None
    assert store.verify(None) is None


def test_expiry(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, rec = store.create("Short", expires_days=1, now=1000)
    assert store.verify(token, now=1000 + 86399) is not None
    assert store.verify(token, now=1000 + 86401) is None


def test_no_expiry_means_never(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, rec = store.create("Forever", now=1000)
    assert rec.expires_at is None
    assert store.verify(token, now=1000 + 10 * 365 * 86400) is not None


def test_last_used_updates_but_not_every_call(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, _ = store.create("Claude", now=1000)
    assert store.verify(token, now=1000).last_used_at == 1000
    assert store.verify(token, now=1010).last_used_at == 1000   # too soon, no write
    assert store.verify(token, now=1100).last_used_at == 1100


def test_delete(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    token, rec = store.create("Claude")
    assert store.delete(rec.id) is True
    assert store.verify(token) is None
    assert store.delete(rec.id) is False


def test_validation(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    for bad in [dict(name=""), dict(name="   "), dict(name="x" * 61),
                dict(name="a", scope="admin"), dict(name="a", expires_days=0), dict(name="a", expires_days=99999)]:
        with pytest.raises(TokenError):
            store.create(**bad)


def test_write_scope_allows_read_but_not_the_other_way(tmp_path):
    store = TokenStore(tmp_path / "t.db")
    _, r = store.create("r", "read")
    _, w = store.create("w", "write")
    assert r.allows("read") and not r.allows("write")
    assert w.allows("read") and w.allows("write")


def test_tokens_survive_restart(tmp_path):
    token, _ = TokenStore(tmp_path / "t.db").create("Claude")
    assert TokenStore(tmp_path / "t.db").verify(token) is not None


# ----- the web routes -----

def test_token_routes_need_login(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_username="mogie", admin_password="secret")
    anon = TestClient(create_app(settings))
    assert anon.get("/api/tokens").status_code == 401
    assert anon.post("/api/tokens", json={"name": "x"}).status_code == 401
    assert anon.delete("/api/tokens/1").status_code == 401


def test_create_list_delete_over_http(tmp_path):
    client = make(tmp_path)
    r = client.post("/api/tokens", json={"name": "Claude", "scope": "write", "worldId": "mcp-test", "expiresDays": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith(PREFIX)
    assert body["info"]["scope"] == "write" and body["info"]["worldId"] == "mcp-test"
    listed = client.get("/api/tokens").json()["tokens"]
    assert len(listed) == 1
    assert "token" not in listed[0] and "hash" not in listed[0]
    assert listed[0]["hint"].startswith(PREFIX[:5])
    assert client.delete(f"/api/tokens/{listed[0]['id']}").status_code == 200
    assert client.get("/api/tokens").json()["tokens"] == []
    assert client.delete(f"/api/tokens/{listed[0]['id']}").status_code == 404


def test_bad_token_form_gives_plain_message(tmp_path):
    client = make(tmp_path)
    r = client.post("/api/tokens", json={"name": ""})
    assert r.status_code == 400
    assert "name" in r.json()["detail"].lower()


# ----- using a token -----

def test_v1_needs_a_token(tmp_path):
    client = make(tmp_path)
    assert client.get("/api/v1/whoami").status_code == 401
    assert client.get("/api/v1/whoami", headers={"x-api-key": "fgat_wrong"}).status_code == 401
    # a logged in web session is not a token
    assert client.post("/api/v1/ping").status_code == 401


def test_v1_whoami_with_header_and_bearer(tmp_path):
    client = make(tmp_path)
    token = client.post("/api/tokens", json={"name": "Claude"}).json()["token"]
    a = client.get("/api/v1/whoami", headers={"x-api-key": token})
    b = client.get("/api/v1/whoami", headers={"authorization": f"Bearer {token}"})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["token"]["name"] == "Claude"


def test_revoked_token_stops_working(tmp_path):
    client = make(tmp_path)
    made = client.post("/api/tokens", json={"name": "Claude"}).json()
    h = {"x-api-key": made["token"]}
    assert client.get("/api/v1/whoami", headers=h).status_code == 200
    client.delete(f"/api/tokens/{made['info']['id']}")
    assert client.get("/api/v1/whoami", headers=h).status_code == 401


def test_v1_ping_with_no_client_is_plain(tmp_path):
    client = make(tmp_path)
    token = client.post("/api/tokens", json={"name": "Claude"}).json()["token"]
    r = client.post("/api/v1/ping", headers={"x-api-key": token})
    assert r.status_code == 502
    assert "No Foundry client" in r.json()["detail"]
