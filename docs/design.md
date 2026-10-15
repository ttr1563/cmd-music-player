# 設計と対応範囲

## 要件

- 対象はYouTube Musicのみ。Spotify / Apple Musicは今回実装しない。
- macOS / Linux / Windowsを設計対象とする。OS実機未検証を対応済みとは扱わない。
- `music`でTUIを起動し、検索、選曲、ライブラリ、プレイリスト、音声再生を操作する。
- 音声はmpvからOS標準の出力先へ送る。TUI終了時はresolverとmpvも終了する。
- 使用アカウントを選択可能。認証は既存browser sessionの必要なheaderのみを明示入力する。
- Keychain / OS credential manager / browser cookie databaseの自動読取りはしない。
- 認証情報は専用領域の暗号化vaultに保存。鍵は起動時のpassphraseから導出し保存しない。
- 保存しないguest利用、ログアウト、全ローカルデータ削除を提供する。

## 責務

- cli: 初回選択、login/account/config/logout/purge/doctor、秘密の非表示入力。
- storage: version付き設定、scrypt + AES-256-GCM vault、原子的保存、所有データだけの削除。
- provider: ytmusicapiによる検索とbrowse。読み取りだけを使い、履歴/評価/playlist書込みはしない。
- resolver: yt-dlpを短命の子processで実行。認証情報はstdin、解決結果はstdoutで受け渡す。
- player: mpvのJSON IPCを利用。秘密をargvへ渡さず、disk cacheとwatch-laterを無効化。
- tui: Textual。network解決中も操作可能。キューはメモリのみ、曲終了で次へ進む。

## 認証・権限・データ

Google passwordは受け取らない。ブラウザで希望のaccountを選び、music.youtube.comの
`browse` requestのCookie / Authorization / X-Goog-Authuserと、
必要な場合のみX-Goog-Pageidを入力する。
ブラウザ側の認証状態と本toolの認証情報は別物。非公式APIのためsession期限切れやGoogle側変更で
再認証が必要になる。loginはaccount情報の取得に成功してから保存する。

全accountを一つの暗号化vaultに保存し、account識別名だけを設定に置く。
salt/nonce/version以外は暗号化し、KDF parameterはコードで固定して外部fileから指定させない。
passphraseを紛失した場合は再認証が必要。復号鍵の自動保存・平文fallbackなし。
POSIXではdirectory 0700/file 0600。WindowsではOSのユーザーディレクトリACLを使用する。
同じOS userや管理者によるメモリ参照、swap/crash dumpまでの無痕跡は保証しない。

永続データは専用ディレクトリのmarker/config.json/vault.encのみ。
音楽、検索履歴、ログ、Cookie平文、一時認証fileは保存しない。
mpv IPC socketはprivate temporary directory内、Windowsはrandom名のnamed pipe。
resolver通信はメモリpipe。外部browserやclipboardはtoolの削除対象外。
yt-dlpのaccount選択は固定versionのextractor adapterでsession index/page IDを指定する。
private API依存のため更新時はこのadapterのtestと複数account実機確認を必須とする。
purgeはmarker確認後に既知のfileだけを消し、未知のfileと他のdirectoryを削除しない。
平文backupの自動生成なし。backupするならvault.encとconfig.jsonを利用者が保管する。

## 互換・失敗・移行・運用

設定/vaultはschema version 1。未知versionを拒否し上書きしない。将来の移行は復号後に
旧形式を検証し、新形式へatomic replaceする。rollbackは旧packageと利用者保管のvaultの組で行う。
ネットワークtimeout、認証拒否、抽出失敗、mpv不足は秘密を含まない案内を表示する。
抽出に失敗した曲を別の動画へ自動置換せず、その曲で停止して利用者に知らせる。
必要実行資源は利用者PCのみ。service/server/公開port/CI/課金サービスは作らない。
同時に音声抽出は1件、network timeout 15秒、resolver全体timeout 45秒を基本とする。
抽出のcancel/timeout/終了時は所有process treeを停止する。POSIXは専用process group、
Windowsはtaskkill /Tを利用する。後者は実機確認が必要。
書込みは短命の.write-lock directoryで排他し、vaultの読取り後に他processが更新した場合は
revision比較で上書きを拒否する。crashで残ったlockは全instance停止後に空directoryだけ削除する。

## 今回実装しないものと拡張境界

- Spotify/Apple Music: ユーザー指定により対象外。providerを分離し、認証と再生条件の確認後に追加。
- 自動OAuthログイン: Google側client設定を要求する方式とbrowser header方式を混ぜない。
  今回は明示的なsession取込み。将来は認証方式とvaultのcredential kindをversion付きで追加する。
- 自動OS依存導入: 管理者権限や既存package managerを勝手に変更しない。doctorとinstall案内で解決。
- OS package managerのuninstall hook: 配布方式未決定のため未実装。アンインストール前にpurge。
- 常駐daemon、別terminalからのremote制御、system media key、download、playlist編集: 現要件外。
  将来daemonを追加する場合はsession寿命、local IPC権限、purge時の停止を先に設計する。

## 参照（2026-10-15）

- https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html
- https://github.com/sigma67/ytmusicapi/blob/main/ytmusicapi/auth/browser.py
- https://github.com/yt-dlp/yt-dlp
- https://mpv.io/manual/stable/#json-ipc
- https://github.com/iwalton3/python-mpv-jsonipc

APIの存在と、各OS/利用者accountで実際に再生できることは区別して記録する。
