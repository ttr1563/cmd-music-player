"""Command entry point. Secrets never enter argv or shell history."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import warnings
import webbrowser
from pathlib import Path

from .audio import output_device
from .provider import YouTubeMusic, login_headers
from .runtime import runtime_description
from .storage import Store, UserError, validate_account


def secret(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise UserError("認証情報の入力には対話terminalが必要です。引数やpipeでは受け取りません。")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning as error:
            raise UserError(
                "非表示入力を利用できません。通常のterminalで再実行してください。"
            ) from error


def unlock(store: Store) -> tuple[dict, str]:
    phrase = secret("認証ファイルのパスフレーズ: ")
    return store.read_vault(phrase), phrase


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def login(store: Store, name: str) -> None:
    validate_account(name)
    if name == "guest":
        raise UserError("guestは未ログイン用の予約名です。別の保存account名を使ってください。")
    accounts, phrase = unlock(store) if store.has_vault() else ({}, "")
    print("music.youtube.comを開き、使用するaccountを選択してください。")
    if confirm("ブラウザを開きますか？"):
        webbrowser.open("https://music.youtube.com")
    print("Networkのbrowse POST requestから次のRequest Headersの値を入力します。")
    print("詳細: READMEの「初回ログイン」。Google passwordは入力しないでください。")
    headers = login_headers(
        secret("Cookie（値だけ・非表示）: ").strip(),
        secret("Authorization（SAPISIDHASH…・非表示）: ").strip(),
        input("X-Goog-Authuser [0]: ").strip() or "0",
        input("X-Goog-Pageid（なければEnter）: ").strip(),
    )
    info = YouTubeMusic(headers).account_info()
    print(f"確認したaccount: {info.get('accountName', '名前なし')}")
    if not confirm(f"このaccountを{name}として保存しますか？"):
        return
    if name in accounts and not confirm("同名の保存accountを置き換えますか？"):
        return
    if not phrase:
        phrase = secret("新しい保存用パスフレーズ（12文字以上）: ")
        if len(phrase) < 12:
            raise UserError("パスフレーズは12文字以上にしてください。")
        if phrase != secret("パスフレーズを再入力: "):
            raise UserError("パスフレーズが一致しません。保存していません。")
    accounts[name] = headers
    store.save_vault(accounts, phrase)
    config = store.read_config()
    config["account"] = name
    store.save_config(config)
    print(f"保存しました: {name}。musicで起動できます。")


def choose_account(store: Store, name: str | None) -> None:
    config = store.read_config()
    if name == "guest":
        config["account"] = None
    else:
        if not store.has_vault():
            raise UserError(
                "保存accountがありません。music login 名前、またはmusic account guestを利用。"
            )
        accounts, _ = unlock(store)
        if name is None:
            names = ["guest", *sorted(accounts)]
            for index, label in enumerate(names, 1):
                print(f"{index}. {label}")
            value = input("使用する番号: ").strip()
            if not value.isdecimal() or not 1 <= int(value) <= len(names):
                raise UserError("一覧の番号を選択してください。")
            name = names[int(value) - 1]
        if name != "guest" and name not in accounts:
            raise UserError("保存されていないaccountです。music accountで確認してください。")
        config["account"] = None if name == "guest" else name
    store.save_config(config)
    print(f"使用account: {config['account'] or 'guest'}")


def doctor(store: Store, audio_test: bool = False) -> int:
    import av
    import miniaudio

    print(f"Python: {sys.version.split()[0]}")
    print(f"データ保存先: {store.directory}")
    print("サービス: YouTube Music / 認証保存: 暗号化file / Keychain: 使用しない")
    print(f"内蔵decoder: PyAV {av.__version__} / 内蔵音声出力: miniaudio {miniaudio.__version__}")
    print(f"JS runtime: {runtime_description()}")
    if audio_test:
        try:
            device = output_device()
            device.close()
            print("OSの標準音声出力を開けました（音は再生していません）。")
        except miniaudio.MiniaudioError:
            print("OSの音声出力を開けません。出力先・デバイスを確認してください。")
            return 1
    print("実accountの認証・実際の音声出力はこの診断では検証しません。")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="YouTube Music terminal player")
    root.add_argument("--data-dir", type=Path, help="専用データ保存先")
    root.add_argument("--guest", action="store_true", help="保存accountを使わず起動")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("doctor", help="依存と保存先を確認").add_argument(
        "--audio",
        action="store_true",
        help="OSの標準音声出力を開けるか確認（無音）",
    )
    commands.add_parser("service", help="サービスを選択")
    commands.add_parser("login", help="選択したbrowser accountの認証を保存").add_argument("name")
    commands.add_parser("account", help="使用accountを変更").add_argument("name", nargs="?")
    commands.add_parser("logout", help="保存accountを削除").add_argument("name")
    commands.add_parser("purge", help="保存データをすべて削除").add_argument(
        "--yes", action="store_true"
    )
    config = commands.add_parser("config", help="設定を表示・変更").add_subparsers(
        dest="config_command",
        required=True,
    )
    config.add_parser("show")
    config.add_parser("path")
    setting = config.add_parser("set")
    setting.add_argument("key", choices=["service", "account", "volume"])
    setting.add_argument("value")
    return root


def run(args: argparse.Namespace) -> int:
    store = Store(args.data_dir)
    store.check()
    if args.command == "doctor":
        return doctor(store, args.audio)
    if args.command == "login":
        login(store, args.name)
    elif args.command == "account":
        choose_account(store, args.name)
    elif args.command == "logout":
        accounts, phrase = unlock(store)
        if args.name not in accounts:
            raise UserError("指定した保存accountはありません。")
        if not confirm(f"保存account {args.name} を削除しますか？"):
            return 0
        del accounts[args.name]
        if accounts:
            store.save_vault(accounts, phrase)
        else:
            store.remove_vault()
        config = store.read_config()
        if config["account"] == args.name:
            config["account"] = None
            store.save_config(config)
        print("ローカルの認証情報を削除しました。browserのログインは変更していません。")
    elif args.command == "purge":
        print(f"削除対象: {store.directory} 内のconfig.jsonとvault.enc")
        print("他のmusicをすべて終了してから実行してください。")
        if args.yes or confirm("設定と保存accountを削除しますか？"):
            store.purge()
            print("アプリ所有の保存データを削除しました。")
    elif args.command == "config":
        if args.config_command == "path":
            print(store.directory / "config.json")
        elif args.config_command == "show":
            print(json.dumps(store.read_config(), indent=2))
        elif args.key == "account":
            choose_account(store, args.value)
        else:
            config = store.read_config()
            try:
                config[args.key] = int(args.value) if args.key == "volume" else args.value
            except ValueError as error:
                raise UserError("volumeは0〜100の整数にしてください。") from error
            store.save_config(config)
    elif args.command == "service":
        print("1. YouTube Music（現在の対応サービス）")
        if input("番号 [1]: ").strip() not in ("", "1"):
            raise UserError("1を選択してください。")
        store.save_config(store.read_config())
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise UserError("TUIは対話terminalで起動してください。")
        config = store.read_config()
        if not args.guest and not (store.directory / "config.json").exists():
            print("サービス: 1. YouTube Music")
            if input("サービス番号 [1]: ").strip() not in ("", "1"):
                raise UserError("1を選択してください。")
            choice = input("1. guestで開始 / 2. login [1]: ").strip()
            if choice == "2":
                login(store, input("保存account名 [personal]: ").strip() or "personal")
                config = store.read_config()
            elif choice not in ("", "1"):
                raise UserError("1か2を選択してください。")
            store.save_config(config)
        headers = None
        if not args.guest and config["account"]:
            accounts, phrase = unlock(store)
            if config["account"] not in accounts:
                raise UserError("選択accountがありません。music account guestで解除してください。")
            headers = accounts[config["account"]]
            del phrase, accounts
        from .tui import MusicApp

        MusicApp(YouTubeMusic(headers), config, guest=args.guest).run()
    return 0


def main() -> None:
    try:
        code = run(parser().parse_args())
    except (UserError, OSError) as error:
        # OSError.strerror does not include file contents or authentication data.
        message = str(error) if isinstance(error, UserError) else error.strerror
        print(f"music: {message}", file=sys.stderr)
        code = 1
    except (KeyboardInterrupt, EOFError):
        print("\n終了しました。", file=sys.stderr)
        code = 130
    sys.exit(code)
