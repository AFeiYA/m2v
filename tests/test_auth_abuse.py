"""Password-account abuse checks. No network and no Supabase."""
import pytest
from fastapi import HTTPException

from src import auth
from src.settings import DEFAULT_SECRET_KEY, assert_saas_secret_configured, get_settings
from tests.test_saas_isolation import sandbox  # noqa: F401


def test_saas_startup_refuses_published_default_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "SECRET_KEY", DEFAULT_SECRET_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        assert_saas_secret_configured()


def test_local_jwt_works_offline_and_is_rejected_on_saas_requests(monkeypatch):
    monkeypatch.setattr(auth, "verify_firebase_id_token", lambda token: None)
    monkeypatch.setattr(auth.settings, "SECRET_KEY", "ci-test-secret-key-not-default")
    token = auth.create_access_token("alice")
    assert auth.decode_token(token)["sub"] == "alice"
    context = auth.saas_request.set(True)
    try:
        with pytest.raises(HTTPException) as exc:
            auth.decode_token(token)
        assert exc.value.status_code == 401
    finally:
        auth.saas_request.reset(context)


def test_legacy_password_register_and_login_are_gone(sandbox):
    body = {"email": "abuse@example.com", "username": "abuse", "password": "password123"}
    assert sandbox.client.post("/api/auth/register", json=body).status_code == 404
    assert sandbox.client.post("/api/auth/login", json={"email": body["email"], "password": body["password"]}).status_code == 404


def test_unverified_non_google_firebase_user_gets_no_account(sandbox, monkeypatch):
    payload = {
        "sub": "unverified-user", "email": "unverified@example.com", "name": "Unverified",
        "type": "access", "provider": "firebase", "email_verified": False,
    }
    monkeypatch.setattr(auth, "decode_token", lambda token: payload)
    response = sandbox.client.get("/api/auth/me", headers={"Authorization": "Bearer unverified"})
    assert response.status_code == 403
    assert response.json()["detail"] == "EMAIL_VERIFICATION_REQUIRED"
    assert auth.signup_bonus_eligible(payload) is False
    assert auth.signup_bonus_eligible({**payload, "email_verified": True}) is True
    assert auth.signup_bonus_eligible({**payload, "sign_in_provider": "google.com"}) is True
