# cmd-music-player

YouTube Musicを検索・選曲して音声だけ再生するCLI/TUIです。
macOS / Linux / Windowsを設計対象とし、Keychainは使いません。
非公式クライアントです。YouTube側の変更・地域・account・認証状態により利用できない曲があります。

## インストール

### バイナリ版（uv・Python・Denoの個別導入不要）

Python・再生library・Denoを含むdirectory一式を配布する構成です。
公開Releaseへの添付はまだ行っていません。Mac/Windows版の生成・実機検証は未完了です。
配布物を受け取った場合は展開後のterminalで実行します。

```console
./music/music doctor
./music/music
```

Windowsでは`music\music.exe`を実行します。POSIX版はsymlinkを保持するtar.gzです。
`music`実行fileだけを移動せず、`_internal`を含むdirectory全体を保持してください。
PATHに配布directoryを追加すると、以降は`music`で起動できます。
更新はアプリ終了後にdirectory一式を差し替えます。問題があれば前版一式へ戻します。
認証/設定の保存形式は共通で、Keychainは使いません。
削除時は`music purge --yes`で専用dataを消してから配布directoryを削除してください。

#### 開発者用ビルド

次の手順は配布物を作る人だけに必要です。聴くPCと同じOS/architecture上で実行します。
Python 3.12とuvを使い、native依存はwheelのみ導入します。

```console
uv sync --locked --group binary --python 3.12 --no-build-package av --no-build-package miniaudio
uv run --locked --group binary python scripts/build_binary.py
uv run --locked --group binary python tests/binary_smoke.py dist/binary-linux-x86_64/music/music
```

`dist/music-0.2.0-<OS>-<architecture>.tar.gz`（Windowsはzip）とSHA256を生成します。
Denoはversionとarchive SHA256を固定して公式配布元から取得し、同梱します。
macOS ARM64（14以上）/Intel、Windows x64、Linux x64がbuild対象です。
Linuxはbuild hostのglibc以上が必要です。別OS向けのcross compileは行いません。
再build時は既存の`dist/binary-<OS>-<architecture>`を別名で保持してから実行します。
同梱license/noticeは保持し、公開前に対象OSのnative libraryのlicense/source要件を確認します。
smokeの対象pathは生成したOS/architectureに合わせ、Windowsでは末尾を`music.exe`にします。
smokeはネット接続・実account・実音声出力を使いません。
Mac版の署名/notarizationは未設定です。GitHub Actionsや有料runnerは追加しません。

### macOSでGitHubから導入する

Homebrew導入済みのMacのターミナルで実行してください。
Homebrewがなければ[公式サイト](https://brew.sh/)の手順で先に導入します。

```console
brew install uv deno
uv tool install --python 3.12 --no-build-package av --no-build-package miniaudio 'https://github.com/ttr1563/cmd-music-player/archive/refs/heads/feature/youtube-music-cli.zip'
uv tool update-shell
```

`uv tool update-shell`の案内に従ってターミナルを開き直し、起動します。
PythonとCLIの依存packageはuvが専用環境へ導入するため、Pythonの個別セットアップは不要です。
uv・Denoの導入は初回だけで、以降は`music`だけで起動できます。
音声再生機能を内蔵しているため、mpvやFFmpegの個別インストールは不要です。

```console
music doctor
music
```

初版は`feature/youtube-music-cli`で配布しています。`main`/`develop`へはまだmergeしていません。
Mac実機の音声出力は未検証です。まずguestで検索を試し、認証要求が出たら
下記「初回ログインとアカウント選択」の手順で`music login personal`を実行してください。
Google passwordやCookieをGitHub issue・chatへ送らないでください。

### Linux / Windows・ローカルソース・wheelから導入する

必要: Python 3.12以上、OSの音声出力環境、インターネット接続。
パッケージはまだ公開していません。このソースを取得したPCのターミナルから実行します。
共有サーバー側にインストールしても手元PCから音は出ません。聴くPCにインストールしてください。

uvがある場合（Python未導入ならuvが対応runtimeを取得）:

```console
uv tool install --python 3.12 --no-build-package av --no-build-package miniaudio /path/to/music-cli
music doctor
music
```

pipxがある場合:

```console
pipx install --python python3.12 --pip-args='--only-binary=av,miniaudio' /path/to/music-cli
music doctor
music
```

配布用wheelを受け取った場合は、ソースdirectoryの代わりにそのfileを指定できます。

```console
uv tool install --python 3.12 --no-build-package av --no-build-package miniaudio /path/to/music_cli_local-0.2.0-py3-none-any.whl
```

PyAV（音声decode）とminiaudio（OSへの出力）のbinary wheelがCLIと一緒に導入されます。
音声エンジンのsource compileを避けるため、上記コマンドでnative packageのbuildを禁止しています。

| OS / CPU | CPython 3.12で利用するbinary wheelの条件 |
| --- | --- |
| macOS / Apple Silicon | macOS 14以上 |
| macOS / Intel | macOS 11以上 |
| Windows / x64 | wheelあり、OSの音声出力環境が必要 |
| Linux / x64 | glibc 2.28以上、PulseAudioまたはALSAが必要 |
| Windows・Linux / ARM64 | miniaudioの該当wheelがないため今回の導入確認対象外 |

表は配布条件であり、各OS実機での動作確認結果ではありません。headless serverへ導入しても
手元PCから音は出ません。音声出力が開けるかは`music doctor --audio`で無音の確認ができます。

yt-dlpとそのPython依存はこのpackageと一緒に入ります。YouTubeのJS challenge解決用に
JS runtimeが必要な場合があり、推奨のDenoがなければdoctorが案内します。
https://github.com/yt-dlp/yt-dlp/wiki/EJS

## 使い方

初回の`music`でYouTube Musicを確認し、guest / loginを選べます。
guestは検索と公開曲の再生を試せます。YouTubeからログイン確認を要求された場合は認証が必要です。
login後は自分のライブラリ/playlistも利用できます。
設定は次回から再利用します。内蔵エンジンとJS runtimeは`music doctor`で確認できます。

```console
music
music --guest
music login personal
music account
music account personal
music account guest
music config show
music config set volume 60
music config set service youtube-music
music config set account personal
music logout personal
```

TUI: 検索欄に入力してEnter → 結果一覧でEnterで再生。
「ライブラリ」「プレイリスト」で自分の曲を表示。「キューに追加」で選択曲を末尾へ追加。
「次へ」、一時停止、停止、前後10秒の移動、音量調整に対応します。
再生中も検索・閲覧ができます。終了はCtrl+Q。最小化中は再生し、TUI終了で再生も終了します。
キュー・検索履歴は保存しません。別terminalからの再生操作は今回未対応です。

## 初回ログインとアカウント選択

Google passwordを本toolに入力しないでください。現在は自動OAuth loginではなく、
ytmusicapiのbrowser認証方式で選択accountの必要なrequest headerを取り込みます。

1. `music login personal`を実行。必要ならbrowserを開く案内を選択。
2. ブラウザで https://music.youtube.com を開き、使いたいGoogle accountへ切り替える。
3. 開発者ツールのNetworkで`/youtubei/v1/browse`宛POST requestを探す。
   見つからなければライブラリを開く。**Request Headers**の値を使う。
4. `Cookie`の値を非表示入力欄に貼る。`Cookie:`という見出しは含めない。
5. 同じrequestの`Authorization`の値（`SAPISIDHASH…`）を非表示欄へ入力。
6. `X-Goog-Authuser`（通常0）、あれば`X-Goog-Pageid`を入力。
7. account情報の取得に成功した後、保存用passphraseを設定。

別accountも別名で取り込み、`music account 名前`で選択します。
Google accountの選択はbrowser上で行います。CLIでGoogle account一覧を取得する方式ではありません。
認証が期限切れなら同じ名前でloginし直します。実際の情報を確認してから置換確認を出します。
ブラウザ側のCookieを変更・削除したり、Keychainから読み取ったりはしません。

認証取込み中だけCookieがclipboardに載ります。作業後は別の文字列をコピーして消してください。
Cookie、request header、vaultのpassphraseをchatやissueへ貼らないでください。
https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html

## 保存・暗号化

保存先は`music config path`で確認できます。

| OS | 既定の専用ディレクトリ |
| --- | --- |
| macOS | `~/Library/Application Support/music-cli` |
| Linux | `$XDG_CONFIG_HOME/music-cli` または `~/.config/music-cli` |
| Windows | `%LOCALAPPDATA%\music-cli` |

`MUSIC_CLI_HOME`または`music --data-dir PATH`で変更できます。
専用領域には`.music-cli`（所有marker）、`config.json`、`vault.enc`だけを保存します。
volume/service/account識別名は平文、認証headerはscrypt + AES-256-GCMで暗号化します。
復号鍵とpassphraseは保存しません。保存accountで起動するとpassphraseを要求します。
passphraseを忘れたら復旧できないので、logout/purge後に再認証してください。

認証情報を引数・環境変数・ログ・平文一時fileへ出しません。
再生エンジンへ渡す一時的なstream URLはlocal IPCで送信します。
OSのswap/crash dumpや同じuser/管理者からのメモリ参照まで防ぐものではありません。
自動backup/telemetry/ネットワーク待受serverはありません。

## データ削除・アンインストール

起動しているmusicをすべて終了してから、同じdata-dir指定で実行してください。

```console
music purge
uv tool uninstall music-cli-local
```

pipxで入れた場合は最後を`pipx uninstall music-cli-local`に置き換えます。
purgeは確認後に既知の保存fileだけを削除します。未知のfileや他のdirectoryは削除しません。
通常のpackage uninstallだけではuser dataは消えません。必ず先にpurgeしてください。
手動で指定した別data-dir、利用者が作ったbackup、browser/clipboardのデータは別途管理してください。
uv/pipxやDenoなど他用途でも使うpackageは自動削除しません。
設定書込み中だけ`.write-lock` directoryを作ります。異常終了で残った場合は、
すべてのmusicを終了し、その空directoryだけを取り除いてから再実行してください。

## GitHub版の更新

同じ開発branchの最新版へ更新する場合は、起動中のmusicを終了して実行します。
認証情報と設定はそのまま残ります。

```console
uv tool install --force --reinstall --refresh --python 3.12 --no-build-package av --no-build-package miniaudio 'https://github.com/ttr1563/cmd-music-player/archive/refs/heads/feature/youtube-music-cli.zip'
music doctor
```

開発branchは更新されます。特定版を固定したい場合はURLを
`https://github.com/ttr1563/cmd-music-player/archive/<commit SHA>.zip`へ置き換えます。
version付きreleaseはまだありません。

## 開発・検証

```console
uv sync --locked
uv run ruff check .
uv run pytest -q
```

依存は`uv.lock`に固定。runtimeの起動は`music`、追加費用が生じるCIやserverは不要です。
設計・今後の境界は[docs/design.md](docs/design.md)を参照。
実accountのログイン/音声出力・macOS/Windowsの実機検証結果は、完了報告とtasks記録を確認してください。
