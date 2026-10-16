import json
import os

import pytest

from music_cli.storage import DEFAULT_CONFIG, Store, UserError


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def test_vault_encrypted_round_trip_and_wrong_password(store):
    accounts = {"personal": {"cookie": "secret-token", "authorization": "private-header"}}
    store.save_vault(accounts, "a long passphrase")
    raw = (store.directory / "vault.enc").read_bytes()
    assert b"secret-token" not in raw and b"private-header" not in raw
    assert store.read_vault("a long passphrase") == accounts
    with pytest.raises(UserError, match="パスフレーズ"):
        store.read_vault("wrong password")
    assert (store.directory / "vault.enc").read_bytes() == raw


def test_authenticated_encryption_rejects_tampering(store):
    store.save_vault({"personal": {"cookie": "test"}}, "passphrase")
    path = store.directory / "vault.enc"
    data = json.loads(path.read_bytes())
    data["data"] = ("A" if data["data"][0] != "A" else "B") + data["data"][1:]
    path.write_text(json.dumps(data))
    with pytest.raises(UserError):
        store.read_vault("passphrase")


def test_does_not_overwrite_concurrent_vault_update(store):
    store.save_vault({"first": {}}, "passphrase")
    second = Store(store.directory)
    stale = second.read_vault("passphrase")
    store.save_vault({"first": {}, "new": {}}, "passphrase")
    with pytest.raises(UserError, match="更新"):
        second.save_vault(stale, "passphrase")
    assert "new" in store.read_vault("passphrase")


def test_read_only_commands_do_not_create_directory(store):
    assert store.read_config() == DEFAULT_CONFIG
    assert not store.has_vault()
    assert not store.directory.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"service": "spotify"},
        {"volume": 101},
        {"volume": True},
        {"account": "../oops"},
    ],
)
def test_invalid_config_not_saved(store, change):
    config = DEFAULT_CONFIG | change
    with pytest.raises(UserError):
        store.save_config(config)
    assert not store.directory.exists()


def test_unknown_vault_version_not_overwritten(store):
    store.ensure()
    path = store.directory / "vault.enc"
    path.write_text('{"version":2}')
    with pytest.raises(UserError, match="未対応"):
        store.read_vault("passphrase")
    with pytest.raises(UserError):
        store.save_vault({}, "passphrase")
    assert path.read_text() == '{"version":2}'


def test_purge_only_owned_data_and_never_unrelated_file(store):
    store.save_config(DEFAULT_CONFIG)
    store.save_vault({"test": {}}, "passphrase")
    other = store.directory / "keep.txt"
    other.write_text("not ours")
    assert set(store.purge()) == {"config.json", "vault.enc"}
    assert other.read_text() == "not ours"
    assert (store.directory / ".music-cli").exists()
    other.unlink()
    store.purge()
    assert not store.directory.exists()


def test_purge_rejects_foreign_directory(tmp_path):
    other = tmp_path / "foreign"
    other.mkdir()
    (other / "config.json").write_text("other app")
    with pytest.raises(UserError):
        Store(other).purge()
    assert (other / "config.json").read_text() == "other app"


def test_symlink_file_is_not_followed_during_purge(store, tmp_path):
    store.save_config(DEFAULT_CONFIG)
    target = tmp_path / "important"
    target.write_text("preserve")
    (store.directory / "vault.enc").symlink_to(target)
    with pytest.raises(UserError, match="symlink"):
        store.purge()
    assert target.read_text() == "preserve"
    assert (store.directory / "config.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_permissions(store):
    store.save_vault({}, "passphrase")
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert (store.directory / "vault.enc").stat().st_mode & 0o777 == 0o600


def test_partial_atomic_write_failure_keeps_existing_data(store, monkeypatch):
    store.save_config(DEFAULT_CONFIG)
    original = (store.directory / "config.json").read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save_config(DEFAULT_CONFIG | {"volume": 10})
    assert (store.directory / "config.json").read_bytes() == original
    assert not list(store.directory.glob(".write-*"))


def test_busy_write_lock_does_not_touch_vault(store):
    store.save_vault({"first": {}}, "passphrase")
    (store.directory / ".write-lock").mkdir()
    with pytest.raises(UserError, match="実行中"):
        store.save_vault({}, "passphrase")
    (store.directory / ".write-lock").rmdir()
    assert "first" in store.read_vault("passphrase")
