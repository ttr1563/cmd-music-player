"""One removable data directory; no OS credential store."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MARKER = "music-cli-local:v1\n"
AAD = b"music-cli-local/vault/v1"
ACCOUNT_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}\Z")
DEFAULT_CONFIG = {"version": 1, "service": "youtube-music", "account": None, "volume": 70}


class UserError(Exception):
    """An error safe to display without revealing credentials."""


def default_directory() -> Path:
    if override := os.environ.get("MUSIC_CLI_HOME"):
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "music-cli"


def validate_account(name: str) -> str:
    if not ACCOUNT_RE.fullmatch(name):
        raise UserError("アカウント名は英数字で始まる40文字以内の英数字・_・-にしてください。")
    return name


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("version") != 1:
        raise UserError("未対応の設定形式です。設定ファイルを上書きしません。")
    if config.get("service") != "youtube-music":
        raise UserError("現在対応しているサービスはyoutube-musicだけです。")
    account = config.get("account")
    if account is not None:
        if not isinstance(account, str):
            raise UserError("accountの設定が不正です。")
        validate_account(account)
    volume = config.get("volume")
    if type(volume) is not int or not 0 <= volume <= 100:
        raise UserError("volumeは0〜100の整数にしてください。")
    return {key: config[key] for key in DEFAULT_CONFIG}


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = (directory or default_directory()).expanduser().absolute()
        self._vault_revision: str | None = None

    @contextmanager
    def _write_lock(self):
        lock = self._path(".write-lock")
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError as error:
            raise UserError(
                "別の設定変更処理が実行中です。終了後に再実行してください。"
                "異常終了後の場合は全musicを終了して.write-lockを確認してください。"
            ) from error
        try:
            yield
        finally:
            lock.rmdir()

    def _vault_digest(self) -> str | None:
        path = self._path("vault.enc")
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    def _path(self, name: str) -> Path:
        path = self.directory / name
        if path.is_symlink():
            raise UserError("データファイルがsymlinkです。操作を中止しました。")
        return path

    def check(self) -> None:
        if self.directory.is_symlink() or self.directory.resolve() in (
            Path.home().resolve(),
            Path(self.directory.anchor),
        ):
            raise UserError("ホーム直下・ルート・symlinkはデータ領域に指定できません。")
        if self.directory.exists():
            marker = self._path(".music-cli")
            if not marker.is_file() or marker.read_text() != MARKER:
                raise UserError(
                    "専用データ領域ではありません。空いている新しいパスを指定してください。"
                )
            if os.name != "nt" and self.directory.stat().st_mode & 0o077:
                raise UserError("データ領域の権限をchmod 700で所有者限定にしてください。")

    def ensure(self) -> None:
        self.check()
        if not self.directory.exists():
            self.directory.mkdir(mode=0o700, parents=True)
            self._write(".music-cli", MARKER.encode())

    def _write(self, name: str, content: bytes) -> None:
        destination = self._path(name)
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read_config(self) -> dict[str, Any]:
        self.check()
        path = self._path("config.json")
        if not path.exists():
            return DEFAULT_CONFIG.copy()
        try:
            return validate_config(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise UserError("設定ファイルが不正です。内容を確認してください。") from error

    def save_config(self, config: dict[str, Any]) -> None:
        data = validate_config(config)
        self.ensure()
        with self._write_lock():
            self._write("config.json", json.dumps(data, indent=2).encode())

    def has_vault(self) -> bool:
        self.check()
        return self._path("vault.enc").is_file()

    @staticmethod
    def _key(passphrase: str, salt: bytes) -> bytes:
        if not passphrase:
            raise UserError("パスフレーズを空にはできません。")
        return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(passphrase.encode())

    def read_vault(self, passphrase: str) -> dict[str, dict[str, str]]:
        self.check()
        if not self.has_vault():
            return {}
        try:
            raw = self._path("vault.enc").read_bytes()
            revision = hashlib.sha256(raw).hexdigest()
            if len(raw) > 2_000_000:
                raise UserError("認証ファイルのサイズが不正です。")
            envelope = json.loads(raw)
            if envelope["version"] != 1:
                raise UserError("未対応の認証ファイル形式です。上書きしません。")
            salt = base64.b64decode(envelope["salt"], validate=True)
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            if len(salt) != 16 or len(nonce) != 12:
                raise ValueError("invalid encryption parameters")
            plaintext = AESGCM(self._key(passphrase, salt)).decrypt(
                nonce,
                base64.b64decode(envelope["data"], validate=True),
                AAD,
            )
            accounts = json.loads(plaintext)
            if not isinstance(accounts, dict):
                raise ValueError("invalid accounts")
            for name, headers in accounts.items():
                validate_account(name)
                if not isinstance(headers, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
                ):
                    raise ValueError("invalid headers")
            self._vault_revision = revision
            return accounts
        except InvalidTag as error:
            raise UserError("パスフレーズが違うか、認証ファイルが破損しています。") from error
        except (ValueError, TypeError, KeyError) as error:
            raise UserError("認証ファイルが不正です。上書きしません。") from error

    def save_vault(self, accounts: dict[str, dict[str, str]], passphrase: str) -> None:
        self.ensure()
        salt, nonce = os.urandom(16), os.urandom(12)
        ciphertext = AESGCM(self._key(passphrase, salt)).encrypt(
            nonce,
            json.dumps(accounts).encode(),
            AAD,
        )
        envelope = {
            "version": 1,
            "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "data": base64.b64encode(ciphertext).decode(),
        }
        with self._write_lock():
            self._check_revision()
            self._write("vault.enc", json.dumps(envelope).encode())
            self._vault_revision = self._vault_digest()

    def _check_revision(self) -> None:
        if self._vault_digest() != self._vault_revision:
            raise UserError(
                "別の処理で認証情報が更新されました。再実行してください。上書きしていません。"
            )

    def remove_vault(self) -> None:
        self.check()
        with self._write_lock():
            self._check_revision()
            self._path("vault.enc").unlink(missing_ok=True)
            self._vault_revision = None

    def purge(self) -> list[str]:
        self.check()
        removed = []
        if self.directory.exists():
            with self._write_lock():
                paths = [self._path(name) for name in ("config.json", "vault.enc")]
                for path in paths:
                    if path.is_file():
                        path.unlink()
                        removed.append(path.name)
            # Keep the ownership marker if unrelated files are present.
            if set(p.name for p in self.directory.iterdir()) == {".music-cli"}:
                self._path(".music-cli").unlink()
                self.directory.rmdir()
        return removed
