# 設計と対応範囲

## 目的と優先順位

festはYouTube Musicをターミナルから検索・選曲・再生するGo製プレイヤーです。
現在はPython版からGo版への移行中です。Python版の追加リリース準備は停止します。

1. CLI・TUI・サービス接続・認証保存・再生制御をGoへ移行します。
2. 既存の操作と設定・暗号化vault v1の互換性を確認します。
3. GPLの部品を含まない再生依存を整備し、各OSの配布を確認します。
4. 確認済みの配布物を公開し、月1回の保守を継続します。

## 完了条件

- Go版festで検索、選曲、キュー、一時停止、音量、シーク、終了ができます。
- guestと保存アカウントを選択でき、ライブラリとプレイリストを読み取れます。
- Keychainを使用せず、旧版と互換のscrypt/AES-256-GCM vaultを使用します。
- Python・uv・Deno・mpvの利用者側インストールを要求しません。
- macOS arm64/amd64・Windows amd64・Linux amd64を対象とします。WindowsはWSL不要です。
- 認証情報・署名URLを引数、ログ、一時ファイルに残しません。
- GPLを含む旧確認用バイナリは公開しません。
- テストとビルド、実サービス接続、実機の音声出力は別々に確認状況を記録します。

## 構成

- CLI/TUI、YouTube Music API接続、URL抽出、設定・認証保存はGoで実装します。
- TUIとネットワーク処理を分離し、検索・曲切替・終了で古い処理をcancelします。
- URL抽出はGo製ライブラリをadapter内に隔離します。YouTube Musicの曲IDのみ受け取り、別動画への自動置換はしません。
- AAC/Opusのデコードは同梱するLGPL構成のFFmpeg、出力はGo音声ライブラリを使用します。
- FFmpegにはメモリpipeから音声を渡します。URL・認証情報をargvへ渡さず、通信はGo側のHTTPS検証とCDN制限を通します。
- FFmpegはアプリが所有する子プロセスとして起動・終了・回収します。利用者による別途導入は不要です。
- decoder/backendを分離し、配布物のhash・license・対応sourceと同じテストで依存更新を確認します。

## 保存・移行・復旧

旧版の保存先、MUSIC_CLI_HOME、marker、config/vault v1、AADとKDF定数を維持します。
未知のschema、symlink、不正なmarker、競合更新は拒否します。設定は原子的に書き換え、purgeは既知の所有ファイルだけ削除します。
秘密は対話端末で非表示入力します。GoogleパスワードやブラウザDBの自動読取り、OS資格情報への保存は行いません。
Go移行でデータ変換は行いません。旧版に戻す場合は全プロセス終了後にアプリ一式を戻します。

## 運用と拡張境界

月次保守はこの設計とホームの共通設定を確認してから実施します。承認前のmerge、リリース、有料実行は行いません。
Spotify/Apple Music、playlist編集、download、常駐daemon、自動OAuthは今回対象外です。provider・credential形式・IPCを分離し、追加時に権限と保存形式を設計します。
署名・公証は未設定です。配布はライセンス資料、実機検証状況、rollbackを明記して行います。
旧実装の経緯はGit履歴とtasks-mdを参照し、現行要件として継承しません。
