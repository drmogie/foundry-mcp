import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.main import create_app
from app.settings import Settings


def make(tmp_path, user="mogie", password="secret"):
    settings = Settings(data_dir=tmp_path, admin_username=user, admin_password=password)
    return TestClient(create_app(settings)), settings


def login(client, user="mogie", password="secret"):
    return client.post("/api/login", json={"username": user, "password": password})


def test_page_is_served(tmp_path):
    client, _ = make(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "FGA Relay" in r.text


def test_session_says_not_configured_without_login(tmp_path):
    client, _ = make(tmp_path, user="", password="")
    body = client.get("/api/session").json()
    assert body["configured"] is False
    assert body["loggedIn"] is False


def test_login_refused_when_not_configured(tmp_path):
    client, _ = make(tmp_path, user="", password="")
    r = login(client)
    assert r.status_code == 403
    assert "Configuration" in r.json()["detail"]


def test_wrong_password_rejected(tmp_path):
    client, _ = make(tmp_path)
    assert login(client, password="nope").status_code == 401


def test_status_needs_login(tmp_path):
    client, _ = make(tmp_path)
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/connect").status_code == 401
    assert client.post("/api/ping").status_code == 401


def test_login_then_status(tmp_path):
    client, _ = make(tmp_path)
    assert login(client).status_code == 200
    assert client.get("/api/session").json()["loggedIn"] is True
    s = client.get("/api/status").json()
    assert s["relay"] == "up"
    assert s["clients"] == []


def test_logout(tmp_path):
    client, _ = make(tmp_path)
    login(client)
    client.post("/api/logout")
    assert client.get("/api/status").status_code == 401


def test_lockout_after_five_wrong_tries(tmp_path):
    client, _ = make(tmp_path)
    for _ in range(5):
        assert login(client, password="bad").status_code == 401
    assert login(client, password="bad").status_code == 429
    assert login(client).status_code == 429  # even the right password waits


def test_connect_info_builds_wss_behind_proxy(tmp_path):
    client, _ = make(tmp_path)
    login(client)
    r = client.get("/api/connect", headers={"x-forwarded-proto": "https", "host": "relay.example.com"})
    body = r.json()
    assert body["url"] == "wss://relay.example.com/ws/module"
    assert body["key"].startswith("fga_")


def test_connect_key_is_stable_and_can_be_replaced(tmp_path):
    client, settings = make(tmp_path)
    login(client)
    first = client.get("/api/connect").json()["key"]
    again, _ = make(tmp_path)
    login(again)
    assert again.get("/api/connect").json()["key"] == first  # survives restart
    new = client.post("/api/connect/regenerate").json()["key"]
    assert new != first


def test_socket_rejects_wrong_key(tmp_path):
    client, _ = make(tmp_path)
    with client.websocket_connect("/ws/module?key=wrong") as ws:
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == 4401


def test_socket_needs_hello_first(tmp_path):
    client, _ = make(tmp_path)
    login(client)
    key = client.get("/api/connect").json()["key"]
    with client.websocket_connect(f"/ws/module?key={key}") as ws:
        ws.send_json({"type": "heartbeat"})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
    assert info.value.code == 4400


def test_session_cookie_helpers():
    cookie = auth.make_session("s3", "mogie", now=1000)
    assert auth.read_session("s3", cookie, now=1001) == "mogie"
    assert auth.read_session("other", cookie, now=1001) is None
    assert auth.read_session("s3", cookie, now=1000 + auth.SESSION_SECONDS + 1) is None
    assert auth.read_session("s3", "junk") is None
    assert auth.read_session("s3", None) is None
