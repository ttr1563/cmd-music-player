# 設計と対応範囲

## 要件

- 対象はYouTube Musicのみ。Spotify / Apple Musicは今回実装しない。
- macOS / Linux / Windowsを設計対象とする。OS実機未検証を対応済みとは扱わない。
- `music`でTUIを起動し、検索、選曲、ライブラリ、プレイリスト、音声再生を操作する。
- 音声は内蔵PyAV decoderとminiaudioからOS標準の出力先へ送る。mpv/FFmpegの外部実行なし。
- TUI終了時はresolverとアプリ所有のaudio workerも終了・reapする。
- 使用アカウントを選択可能。認証は既存browser sessionの必要なheaderのみを明示入力する。
- Keychain / OS credential manager / browser cookie databaseの自動読取りはしない。
- 認証情報は専用領域の暗号化vaultに保存。鍵は起動時のpassphraseから導出し保存しない。
- 保存しないguest利用、ログアウト、全ローカルデータ削除を提供する。

## 責務

- cli: 初回選択、login/account/config/logout/purge/doctor、秘密の非表示入力。
- storage: version付き設定、scrypt + AES-256-GCM vault、原子的保存、所有データだけの削除。
- provider: ytmusicapiによる検索とbrowse。読み取りだけを使い、履歴/評価/playlist書込みはしない。
- resolver: yt-dlpを短命の子processで実行。認証情報はstdin、解決結果はstdoutで受け渡す。
- player: URL取得と再生workerのlifecycleを調整する。秘密をargvへ渡さない。
- transport: Requestsの証明書/hostname検証、接続10秒/read5秒、CDN内HTTPS redirect最大5回、
  HTTP Range検証、read最大64KiB。切断を正常EOFとして扱わない。
- engine: spawn方式のworkerをprivate memory pipeで操作。音声URLもpipeへ渡す。
- audio: PyAVでAAC/Opus等を48kHz/stereo/float32にdecodeし、miniaudioへ出力。
  decodeは1 thread、device callbackはnetwork/seekを行わずPCM bufferだけを読む。
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
resolverとaudio workerの通信はメモリpipe。socket fileや平文media一時fileを作らない。
外部browserやclipboardはtoolの削除対象外。
yt-dlpのaccount選択は固定versionのextractor adapterでsession index/page IDを指定する。
private API依存のため更新時はこのadapterのtestと複数account実機確認を必須とする。
purgeはmarker確認後に既知のfileだけを消し、未知のfileと他のdirectoryを削除しない。
平文backupの自動生成なし。backupするならvault.encとconfig.jsonを利用者が保管する。

## 互換・失敗・移行・運用

設定/vaultはschema version 1。未知versionを拒否し上書きしない。将来の移行は復号後に
旧形式を検証し、新形式へatomic replaceする。rollbackは旧packageと利用者保管のvaultの組で行う。
ネットワークtimeout、認証拒否、抽出失敗、音声デバイス失敗は秘密を含まない案内を表示する。
抽出に失敗した曲を別の動画へ自動置換せず、その曲で停止して利用者に知らせる。
必要実行資源は利用者PCのみ。service/server/公開port/CI/課金サービスは作らない。
同時に音声抽出は1件、network timeout 15秒、resolver全体timeout 45秒を基本とする。
抽出のcancel/timeout/終了時は所有process treeを停止する。POSIXは専用process group、
Windowsはtaskkill /Tを利用する。後者は実機確認が必要。
audio workerは0.3秒の終了待ち後にterminate、さらに2秒でkill、最後に2秒待ってreapする。
PCM bufferは最大2秒（768,000 bytes）。pause時はconsumeせず、volumeはPCM gainで適用。
seek時は世代番号で古いdecode結果を拒否し、HTTP Rangeで位置を変更する。seek不可は曲を停止して通知。
EOFはdevice bufferを流してから通知。callback停止も検出し、無音のnull backendへ自動fallbackしない。
native libraryのraw logは抑制し、固定error codeだけを親へ渡す。
書込みは短命の.write-lock directoryで排他し、vaultの読取り後に他processが更新した場合は
revision比較で上書きを拒否する。crashで残ったlockは全instance停止後に空directoryだけ削除する。

## 配布と移行（0.2.0）

Python>=3.12、PyAV19.0.1/miniaudio1.71のbinary wheelを利用。Mac ARM64は14以上、
Intelは11以上。Windows x64/Linux x64はwheel条件をREADMEへ記載。
Windows/Linux ARM64はminiaudio wheelがなく今回の保証外。対応はwheel供給または専用build/検証環境の
整備後に追加し、利用者PCでnative compileを暗黙に開始しないようinstall commandにno-build-packageを付ける。
PyAVのFFmpeg依存とminiaudioは依存packageの配布物として取得し、外部mpvを探す経路は削除する。
source/wheel導入に加え、PyInstaller onedirのstandalone配布を用意する。
Python、native library、EJS、version/SHA256固定のDenoを同梱し、利用者側のuv/Python/Denoを不要にする。
runtime moduleが同梱Denoの絶対pathを返し、resolverは同じ実行fileの専用modeで起動する。
entrypointのfreeze_supportでaudio worker/resource trackerをCLI起動前に振り分ける。
単一fileへの毎回展開を避けるためdirectory一式を配布し、POSIX tar.gzでsymlinkを保持する。
buildは対象OS/architecture上で行い、Mac/Windows環境がない段階では生成・実機検証を完了扱いにしない。
dependency metadata/license、Python/Denoのlicense、固定lockを同梱する。
公開binary release前にFFmpeg等の実際のnative依存のlicense/source/relinking要件を別途確認する。
署名/notarization・自動updateは未実装。OS別の署名環境と配布経路が必要。
Mac hosted buildは通常push/PR作成では走らないlabel起動のみとし、owner全体の費用確認後に開始する。
標準Mac runnerを2architecture直列で使い、対象commit一致かつdraftであるReleaseにのみ添付する。
従量のActions artifact/cache storage、有料large runner、公開操作、tag作成は行わない。
install.shはMac archiveのSHA256/architecture/形式を確認してuser領域へ展開し、専用bundleを保持する。
既存の他commandは上書きせず、旧bundleを残してrollback可能にする。

保存設定/vault v1は移行不要。0.1.0からの更新はREADMEのforce/reinstall/refresh手順を使用。
rollbackは`dcad5ff56833375edc7f4a583b803a35f3aa3b0c`のarchiveを再installし、旧版に必要なmpvを用意する。
old/new同時起動と、起動中のupdate/purgeは行わない。旧依存をtool側からOS全体へuninstallしない。
doctorはlibraryとJS runtimeの確認、doctor --audioはdeviceを開けるか無音の確認を提供する。
standalone更新/rollbackは全process終了後にdirectory一式を差し替える。保存schemaは同一で移行不要。
build失敗時の部分生成物を成功扱いにせず、既存出力の自動上書きも拒否する。
配布archiveのSHA256と、PATHを空にしたdoctor/config/purge/resolver/Deno、frozen worker起動を検証する。

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
- https://github.com/PyAV-Org/PyAV
- https://github.com/irmen/pyminiaudio
- https://pypi.org/project/av/19.0.1/
- https://pypi.org/project/miniaudio/1.71/
- https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification

APIの存在と、各OS/利用者accountで実際に再生できることは区別して記録する。
