def test_password_hash_roundtrip():
    from app.security import hash_password, verify_password

    h = hash_password("hunter22")
    assert h != "hunter22"
    assert verify_password("hunter22", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    from app.security import create_access_token, decode_access_token

    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_jwt_invalid_token_returns_none():
    from app.security import decode_access_token

    assert decode_access_token("garbage") is None


def test_fernet_roundtrip():
    from app.security import decrypt_secret, encrypt_secret

    enc = encrypt_secret("sk-abc123")
    assert enc != "sk-abc123"
    assert decrypt_secret(enc) == "sk-abc123"


def test_fernet_missing_key_raises_clear_error(monkeypatch):
    import pytest

    from app import security

    monkeypatch.setattr(security.settings, "fernet_key", "")
    with pytest.raises(RuntimeError, match="FERNET_KEY"):
        security.encrypt_secret("x")
