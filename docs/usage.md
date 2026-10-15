# 詳しい使い方

[READMEに戻る](../README.md)

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
passphraseを忘れた場合は復旧できません。purgeで保存データを削除してから再認証してください。

認証情報を引数・環境変数・ログ・平文一時fileへ出しません。
再生エンジンへ渡す一時的なstream URLはlocal IPCで送信します。
OSのswap/crash dumpや同じuser/管理者からのメモリ参照まで防ぐものではありません。
自動backup/telemetry/ネットワーク待受serverはありません。

## データ削除・アンインストール

起動しているmusicをすべて終了してから、同じdata-dir指定で実行してください。

```console
music purge
```

purgeは確認後に既知の保存fileだけを削除します。未知のfileや他のdirectoryは削除しません。
アプリ本体の削除だけでは保存データは消えません。先にpurgeしてください。
手動で指定した別data-dir、利用者が作ったbackup、browser/clipboardのデータは別途管理してください。
uv/pipxやDenoなど他用途でも使うpackageは自動削除しません。
設定書込み中だけ`.write-lock` directoryを作ります。異常終了で残った場合は、
すべてのmusicを終了し、その空directoryだけを取り除いてから再実行してください。


Macの`install.sh`で導入したアプリ本体は、purge後に次のように削除できます。
標準の保存先へ導入した場合の手順です。

```console
rm "$HOME/.local/bin/music"
rm -rf "$HOME/.local/share/music-cli"
```

`MUSIC_INSTALL_PREFIX`を指定して導入した場合は、その配置先を削除してください。
uv/pipxで導入した場合は、それぞれ`uv tool uninstall music-cli-local`、
`pipx uninstall music-cli-local`でアプリ本体を削除します。
