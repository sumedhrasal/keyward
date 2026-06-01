"""Encrypted file-based secret store for headless environments.

Activated automatically when KEYWARD_MASTER_PASSWORD is set in the environment.
Secrets are stored in ~/.config/keyward/secrets.enc, encrypted with Fernet using
a key derived from the master password via PBKDF2-SHA256 (480k iterations).
A 16-byte random salt is prepended to the ciphertext and reused across writes.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from keyward.config import config_dir

_ITERATIONS = 480_000
_SALT_LEN = 16


def _fernet(salt: bytes) -> Fernet:
    password = os.environ["KEYWARD_MASTER_PASSWORD"].encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return Fernet(key)


def _path():
    return config_dir() / "secrets.enc"


def _load() -> dict[str, str]:
    p = _path()
    if not p.exists():
        return {}
    raw = p.read_bytes()
    salt, ciphertext = raw[:_SALT_LEN], raw[_SALT_LEN:]
    try:
        data = _fernet(salt).decrypt(ciphertext)
    except InvalidToken as e:
        raise RuntimeError("KEYWARD_MASTER_PASSWORD is wrong or the secrets file is corrupt") from e
    return json.loads(data)


def _save(store: dict[str, str]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Reuse existing salt so the derived key stays consistent across writes.
    salt = p.read_bytes()[:_SALT_LEN] if p.exists() else os.urandom(_SALT_LEN)
    p.write_bytes(salt + _fernet(salt).encrypt(json.dumps(store).encode()))
    p.chmod(0o600)


def set_password(service: str, name: str, secret: str) -> None:
    s = _load()
    s[f"{service}/{name}"] = secret
    _save(s)


def get_password(service: str, name: str) -> str | None:
    return _load().get(f"{service}/{name}")


def delete_password(service: str, name: str) -> None:
    s = _load()
    s.pop(f"{service}/{name}", None)
    _save(s)
