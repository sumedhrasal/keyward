from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from keyward import filestore


@pytest.fixture(autouse=True)
def master_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEYWARD_MASTER_PASSWORD", "test-master-password")


def test_set_and_get(isolated_env: Path) -> None:
    filestore.set_password("svc", "key1", "secret1")
    assert filestore.get_password("svc", "key1") == "secret1"


def test_get_missing_returns_none(isolated_env: Path) -> None:
    assert filestore.get_password("svc", "nonexistent") is None


def test_delete(isolated_env: Path) -> None:
    filestore.set_password("svc", "key1", "secret1")
    filestore.delete_password("svc", "key1")
    assert filestore.get_password("svc", "key1") is None


def test_delete_missing_is_noop(isolated_env: Path) -> None:
    filestore.delete_password("svc", "nonexistent")


def test_multiple_keys(isolated_env: Path) -> None:
    filestore.set_password("svc", "a", "aaa")
    filestore.set_password("svc", "b", "bbb")
    assert filestore.get_password("svc", "a") == "aaa"
    assert filestore.get_password("svc", "b") == "bbb"


def test_overwrite(isolated_env: Path) -> None:
    filestore.set_password("svc", "key1", "old")
    filestore.set_password("svc", "key1", "new")
    assert filestore.get_password("svc", "key1") == "new"


def test_wrong_password_raises(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    filestore.set_password("svc", "key1", "secret1")
    monkeypatch.setenv("KEYWARD_MASTER_PASSWORD", "wrong-password")
    with pytest.raises(RuntimeError, match="wrong or the secrets file is corrupt"):
        filestore.get_password("svc", "key1")


def test_file_is_not_plaintext(isolated_env: Path) -> None:
    filestore.set_password("svc", "key1", "supersecret")
    raw = (isolated_env / "config" / "keyward" / "secrets.enc").read_bytes()
    assert b"supersecret" not in raw


def test_file_permissions(isolated_env: Path) -> None:
    filestore.set_password("svc", "key1", "secret1")
    p = isolated_env / "config" / "keyward" / "secrets.enc"
    assert oct(p.stat().st_mode)[-3:] == "600"
