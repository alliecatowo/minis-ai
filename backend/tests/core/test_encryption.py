import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from app.core import encryption
from app.core.config import settings


@pytest.fixture(autouse=True)
def reset_encryption_settings(monkeypatch):
    original_key = settings.encryption_key
    original_jwt_secret = settings.jwt_secret
    encryption._reset_encryption_cache()
    yield
    monkeypatch.setattr(settings, "encryption_key", original_key)
    monkeypatch.setattr(settings, "jwt_secret", original_jwt_secret)
    encryption._reset_encryption_cache()


def test_encrypt_decrypt_with_explicit_key(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "test-explicit-encryption-key")
    encryption._reset_encryption_cache()

    ciphertext = encryption.encrypt_value("user-api-key")

    assert ciphertext != "user-api-key"
    assert encryption.decrypt_value(ciphertext) == "user-api-key"


def test_missing_key_fails_closed_without_secret_leak(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-secret-must-not-be-used")
    encryption._reset_encryption_cache()

    with pytest.raises(encryption.EncryptionConfigurationError) as excinfo:
        encryption.encrypt_value("user-api-key")

    message = str(excinfo.value)
    assert "ENCRYPTION_KEY" in message
    assert "jwt-secret-must-not-be-used" not in message
    assert "user-api-key" not in message


def test_validate_required_config_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "")

    with pytest.raises(encryption.EncryptionConfigurationError):
        encryption.validate_encryption_config(required=True)


def test_validate_optional_config_allows_missing_key_until_use(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "")

    encryption.validate_encryption_config(required=False)

    with pytest.raises(encryption.EncryptionConfigurationError):
        encryption.decrypt_value("not-used")


def test_legacy_jwt_secret_derived_token_is_not_decrypted(monkeypatch):
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(b"legacy-jwt-secret").digest())
    legacy_token = Fernet(legacy_key).encrypt(b"legacy-user-api-key").decode()

    monkeypatch.setattr(settings, "encryption_key", "")
    monkeypatch.setattr(settings, "jwt_secret", "legacy-jwt-secret")
    encryption._reset_encryption_cache()

    with pytest.raises(encryption.EncryptionConfigurationError):
        encryption.decrypt_value(legacy_token)
