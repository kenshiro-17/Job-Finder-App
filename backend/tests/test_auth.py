from app.auth import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_roundtrip():
    password = "strong-pass-123"
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(42)
    user_id = decode_access_token(token)
    assert user_id == 42
