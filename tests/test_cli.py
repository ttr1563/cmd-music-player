from unittest.mock import Mock

import pytest

from music_cli.cli import choose_account, doctor, login, parser, run, secret
from music_cli.storage import DEFAULT_CONFIG, Store, UserError


def test_help_and_usage_use_fest():
    assert parser().prog == "fest"
    assert parser().format_usage().startswith("usage: fest ")


def test_cli_configuration_and_purge_leave_no_app_data(tmp_path, capsys):
    directory = tmp_path / "data"
    prefix = ["--data-dir", str(directory)]
    run(parser().parse_args([*prefix, "config", "set", "volume", "40"]))
    run(parser().parse_args([*prefix, "config", "show"]))
    assert '"volume": 40' in capsys.readouterr().out
    run(parser().parse_args([*prefix, "purge", "--yes"]))
    assert not directory.exists()


def test_account_selection_does_not_delete_other_accounts(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    store.save_vault({"personal": {"cookie": "one"}, "work": {"cookie": "two"}}, "passphrase")
    monkeypatch.setattr("music_cli.cli.secret", lambda _: "passphrase")
    choose_account(store, "work")
    assert store.read_config()["account"] == "work"
    assert len(store.read_vault("passphrase")) == 2
    choose_account(store, "guest")
    assert store.read_config()["account"] is None


def test_failed_login_does_not_create_credentials(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    monkeypatch.setattr("music_cli.cli.confirm", lambda _: False)
    monkeypatch.setattr("builtins.input", lambda _: "0")
    monkeypatch.setattr("music_cli.cli.login_headers", lambda *args: {"cookie": "secret"})
    monkeypatch.setattr("music_cli.cli.secret", lambda _: "synthetic")
    monkeypatch.setattr(
        "music_cli.cli.YouTubeMusic",
        Mock(
            return_value=Mock(account_info=Mock(side_effect=UserError("認証拒否"))),
        ),
    )
    with pytest.raises(UserError):
        login(store, "personal")
    assert not store.directory.exists()


def test_logout_only_removes_target_account(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    store = Store(directory)
    store.save_vault({"one": {}, "two": {}}, "passphrase")
    store.save_config(DEFAULT_CONFIG | {"account": "one"})
    monkeypatch.setattr("music_cli.cli.secret", lambda _: "passphrase")
    monkeypatch.setattr("music_cli.cli.confirm", lambda _: True)
    run(parser().parse_args(["--data-dir", str(directory), "logout", "one"]))
    assert Store(directory).read_vault("passphrase") == {"two": {}}
    assert store.read_config()["account"] is None


def test_secret_rejects_piped_input_without_echoing(monkeypatch):
    monkeypatch.setattr("music_cli.cli.sys.stdin.isatty", lambda: False)
    with pytest.raises(UserError, match="対話terminal"):
        secret("test")


def test_doctor_does_not_require_mpv_or_open_the_audio_device(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("music_cli.runtime.shutil.which", lambda _: None)
    device = Mock()
    monkeypatch.setattr("music_cli.cli.output_device", device)
    store = Store(tmp_path / "unused")
    assert doctor(store) == 0
    device.assert_not_called()
    assert "PyAV" in capsys.readouterr().out
    assert not store.directory.exists()


def test_explicit_audio_diagnostic_handles_device_failure(tmp_path, monkeypatch, capsys):
    import miniaudio

    monkeypatch.setattr(
        "music_cli.cli.output_device",
        Mock(
            side_effect=miniaudio.MiniaudioError("raw platform detail"),
        ),
    )
    assert doctor(Store(tmp_path / "unused"), audio_test=True) == 1
    output = capsys.readouterr().out
    assert "raw platform detail" not in output and "開けません" in output
