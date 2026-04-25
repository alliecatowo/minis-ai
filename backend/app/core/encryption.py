import base64
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings


class EncryptionConfigurationError(RuntimeError):
    """Raised when encrypted secrets are requested without explicit key config."""


def _derive_key(secret: str) -> bytes:
    explicit_secret = secret.strip()
    if not explicit_secret:
        raise EncryptionConfigurationError(
            "ENCRYPTION_KEY must be set to use encrypted user secrets."
        )

    derived = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=b"minis-encryption-key",
    ).derive(explicit_secret.encode())
    return base64.urlsafe_b64encode(derived)


def validate_encryption_config(*, required: bool = False) -> None:
    """Validate encryption config without logging or exposing secret material."""
    if required or settings.encryption_key.strip():
        _derive_key(settings.encryption_key)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.encryption_key))


def _reset_encryption_cache() -> None:
    """Clear cached key material after tests mutate settings."""
    _get_fernet.cache_clear()


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
