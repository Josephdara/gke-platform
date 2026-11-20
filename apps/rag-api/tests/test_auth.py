from fastapi.testclient import TestClient
import pytest

from rag_api.auth import COOKIE, AuthConfigError, Sessions, User, hash_password, load_key, load_users, verify_password

from conftest import HEADERS, PASSWORDS, signed_in


def test_password_hashes_verify_and_differ():
    first, second = hash_password("a long password"), hash_password("a long password")
    assert first != second and first.startswith("scrypt$32768$8$1$")
    assert verify_password("a long password", first)
    assert not verify_password("a long passwordX", first)
    assert not verify_password("anything", "plain-text")


def test_cookies_expire_and_cannot_be_forged():
    clock = [1_000.0]
    user = User("tester", hash_password("x" * 12))
    sessions = Sessions({"tester": user}, b"k" * 32, 3600, clock=lambda: clock[0])
    cookie = sessions.issue(user)
    assert sessions.check(cookie) == user
    payload, signature = cookie.split(".")
    assert sessions.check(f"{payload}.{signature[:-2]}AA") is None
    assert Sessions({"tester": user}, b"z" * 32, 3600).check(cookie) is None
    assert sessions.check("not-a-cookie") is None
    clock[0] += 3600
    assert sessions.check(cookie) is None
    # A user removed from the users file loses access at once.
    clock[0] = 1_000.0
    assert Sessions({}, b"k" * 32, 3600, clock=lambda: clock[0]).check(cookie) is None


def test_bad_users_file_or_key_stops_startup(tmp_path):
    (tmp_path / "users.json").write_text('{"users": [{"username": "a", "passwordHash": "plain"}]}')
    (tmp_path / "key").write_text("short")
    with pytest.raises(AuthConfigError):
        load_users(str(tmp_path / "users.json"))
    with pytest.raises(AuthConfigError):
        load_key(str(tmp_path / "key"))


def test_sign_in_sets_a_strict_http_only_cookie(make_app, model):
    with TestClient(make_app(model), headers=HEADERS) as client:
        response = client.post("/api/session", json={"username": "tester", "password": PASSWORDS["tester"]})
        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=28800" in cookie
        assert client.get("/api/session").json() == {"username": "tester"}
        assert client.delete("/api/session").status_code == 204
        assert client.get("/api/session").status_code == 401


def test_wrong_username_and_wrong_password_look_the_same(make_app, model):
    with TestClient(make_app(model), headers=HEADERS) as client:
        wrong_password = client.post("/api/session", json={"username": "tester", "password": "nope"})
        no_user = client.post("/api/session", json={"username": "nobody", "password": "nope"})
    assert wrong_password.status_code == no_user.status_code == 401
    assert wrong_password.json() == no_user.json() == {"detail": "invalid_credentials"}


def test_sign_in_attempts_are_throttled(make_app, model):
    with TestClient(make_app(model), headers=HEADERS) as client:
        codes = [client.post("/api/session", json={"username": "tester", "password": "nope"}).status_code for _ in range(6)]
        blocked = client.post("/api/session", json={"username": "tester", "password": PASSWORDS["tester"]})
    assert codes == [401] * 5 + [429]
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


@pytest.mark.parametrize("headers", [
    {"X-Assistant-Client": "1"},
    {"Origin": "https://evil.example", "X-Assistant-Client": "1"},
    {"Origin": "http://testserver"},
])
def test_state_changes_need_the_origin_and_the_custom_header(make_app, model, headers):
    app = make_app(model)
    with signed_in(app) as client:
        for method, path, body in [("POST", "/api/chat", {"question": "Why?"}), ("DELETE", "/api/session", None),
                                   ("POST", "/api/session", {"username": "tester", "password": PASSWORDS["tester"]})]:
            client.headers.clear()
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 403, (method, path)
    assert model.chat_bodies == []


def test_every_api_route_except_sign_in_needs_a_session(make_app, model):
    with TestClient(make_app(model), headers=HEADERS) as client:
        for method, path in [("GET", "/api/status"), ("GET", "/api/conversations"), ("POST", "/api/chat"),
                             ("GET", "/api/sources/1-0123456789ab-0"), ("GET", "/api/session")]:
            response = client.request(method, path, json={"question": "Why?"} if method == "POST" else None)
            assert response.status_code == 401, path


def test_the_benchmark_account_skips_the_rate_limit_but_not_admission(make_app, model):
    app = make_app(model, rate_limit_per_minute=1)
    with signed_in(app, "benchmark") as client:
        assert [client.post("/api/chat", json={"question": "Why?"}).status_code for _ in range(3)] == [200, 200, 200]
        for _ in range(3):
            app.state.admission.try_acquire()
        assert client.post("/api/chat", json={"question": "Why?"}).status_code == 429
