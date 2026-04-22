from __future__ import annotations

import datetime as dt
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


def config_file() -> Path:
    return config_dir() / "config.toml"


@dataclass
class KeyEntry:
    name: str
    token: str
    endpoint: str
    env_vars: list[str] = field(default_factory=list)
    base_url_env: str | None = None
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "token": self.token,
            "endpoint": self.endpoint,
            "env_vars": self.env_vars,
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
) -> KeyEntry:
    if get_key(name) is not None:
        raise KeyError(f"key '{name}' already exists; use 'keyward rotate' to change its secret")
    keyring.set_password(KEYCHAIN_SERVICE, name, secret)
    entry = KeyEntry(
        name=name,
        token=mint_token(),
        endpoint=endpoint,
        env_vars=env_vars,
        base_url_env=base_url_env,
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
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
    return True


def rotate_secret(name: str, new_secret: str) -> KeyEntry | None:
    entry = get_key(name)
    if entry is None:
        return None
    keyring.set_password(KEYCHAIN_SERVICE, name, new_secret)
    return entry


def read_secret(name: str) -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, name)
