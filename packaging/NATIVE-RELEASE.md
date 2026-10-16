# Go版の配布

対象OSで`go run ./cmd/fest-build`を実行します。アプリ本体はGo、音声decoderはLGPL構成のFFmpegです。
macOS arm64/amd64、Windows amd64、Linux amd64を対象とします。WindowsはWSL不要です。

配布フォルダは`fest`実行ファイル、`runtime/`、`notices/`です。アーカイブ、SHA-256、対応ソースを一緒に配布します。
Python版の確認用draftは公開しません。署名・公証は未設定です。

通常のpushではネイティブビルドを実行しません。既存の同一commitを指定したdraftへ、明示ラベルで対象OSだけを直列ビルドします。
公開標準ランナー、各20分上限、Actions cache/artifactなし、追加課金0を条件とします。所有者全体の利用量を確認してから起動します。

テスト、各OSビルド、実サービス接続、ログイン、実機音声出力の結果を区別します。
公開前に対応ソース、依存ライセンス、展開後の起動と再生、終了時の子プロセス回収を確認します。
公開はPRの承認・mainへのマージ後です。失敗時は全festを終了して旧アプリ一式へ戻します。設定・vault v1の変換は不要です。
