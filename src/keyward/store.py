from __future__ import annotations

import contextlib
import datetime as dt
import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import keyring
import keyring.errors
import tomli_w

from keyward.config import config_dir, ensure_dirs

KEYCHAIN_SERVICE = "keyward"


def _use_filestore() -> bool:
    return bool(os.environ.get("KEYWARD_MASTER_PASSWORD"))


def _set_secret(name: str, secret: str) -> None:
    if _use_filestore():
        from keyward import filestore

        filestore.set_password(KEYCHAIN_SERVICE, name, secret)
        return
    try:
        keyring.set_password(KEYCHAIN_SERVICE, name, secret)
    except keyring.errors.KeyringLocked as e:
        raise RuntimeError(
            "system keyring is locked. Set KEYWARD_MASTER_PASSWORD to use the encrypted file backend instead."
        ) from e


def _get_secret(name: str) -> str | None:
    if _use_filestore():
        from keyward import filestore

        return filestore.get_password(KEYCHAIN_SERVICE, name)
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, name)
    except keyring.errors.KeyringLocked as e:
        raise RuntimeError(
            "system keyring is locked. Set KEYWARD_MASTER_PASSWORD to use the encrypted file backend instead."
        ) from e


def _delete_secret(name: str) -> None:
    if _use_filestore():
        from keyward import filestore

        filestore.delete_password(KEYCHAIN_SERVICE, name)
        return
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(KEYCHAIN_SERVICE, name)


def config_file() -> Path:
    return config_dir() / "config.toml"


AUTH_STYLES = ("bearer", "x-api-key")
ALLOWED_SCHEMES = ("http", "https")


def _validate_endpoint(endpoint: str) -> None:
    if "://" in endpoint:
        scheme = endpoint.split("://", 1)[0].lower()
        if scheme not in ALLOWED_SCHEMES:
            raise ValueError(f"endpoint scheme must be one of {ALLOWED_SCHEMES}, got {scheme!r}")


@dataclass
class KeyEntry:
    name: str
    token: str
    endpoint: str
    env_vars: list[str] = field(default_factory=list)
    base_url_env: str | None = None
    auth_style: str = "bearer"
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "token": self.token,
            "endpoint": self.endpoint,
            "env_vars": self.env_vars,
            "auth_style": self.auth_style,
            "created": self.created,
        }
        if self.base_url_env:
            d["base_url_env"] = self.base_url_env
        return d

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> KeyEntry:
        return cls(
            name=name,
            token=d["token"],
            endpoint=d["endpoint"],
            env_vars=list(d.get("env_vars", [])),
            base_url_env=d.get("base_url_env"),
            # default to bearer for configs written before auth_style existed
            auth_style=d.get("auth_style", "bearer"),
            created=d.get("created", ""),
        )


def mint_token() -> str:
    return "kw_" + secrets.token_hex(8)


def _load_raw() -> dict[str, Any]:
    path = config_file()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _save_raw(data: dict[str, Any]) -> None:
    ensure_dirs()
    with config_file().open("wb") as f:
        tomli_w.dump(data, f)


def list_keys() -> list[KeyEntry]:
    data = _load_raw()
    return [KeyEntry.from_dict(n, d) for n, d in data.get("keys", {}).items()]


def get_key(name: str) -> KeyEntry | None:
    data = _load_raw()
    d = data.get("keys", {}).get(name)
    return KeyEntry.from_dict(name, d) if d else None


def get_key_by_token(token: str) -> KeyEntry | None:
    for k in list_keys():
        if k.token == token:
            return k
    return None


def add_key(
    name: str,
    secret: str,
    endpoint: str,
    env_vars: list[str],
    base_url_env: str | None,
    auth_style: str = "bearer",
) -> KeyEntry:
    if auth_style not in AUTH_STYLES:
        raise ValueError(f"auth_style must be one of {AUTH_STYLES}, got {auth_style!r}")
    _validate_endpoint(endpoint)
    if get_key(name) is not None:
        raise KeyError(f"key '{name}' already exists; use 'keyward rotate' to change its secret")
    _set_secret(name, secret)
    entry = KeyEntry(
        name=name,
        token=mint_token(),
        endpoint=endpoint,
        env_vars=env_vars,
        base_url_env=base_url_env,
        auth_style=auth_style,
        created=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    )
    data = _load_raw()
    data.setdefault("keys", {})[name] = entry.to_dict()
    _save_raw(data)
    return entry


def remove_key(name: str) -> bool:
    data = _load_raw()
    keys = data.get("keys", {})
    if name not in keys:
        return False
    del keys[name]
    _save_raw(data)
    _delete_secret(name)
    return True


def rotate_secret(name: str, new_secret: str) -> KeyEntry | None:
    entry = get_key(name)
    if entry is None:
        return None
    _set_secret(name, new_secret)
    return entry


def read_secret(name: str) -> str | None:
    return _get_secret(name)
