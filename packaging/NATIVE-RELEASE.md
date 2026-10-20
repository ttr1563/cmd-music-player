# 配布

対象OSで`go run ./cmd/fest-build`を実行します。Go本体とLGPL構成のFFmpegを同梱します。
macOS arm64/amd64・Windows amd64・Linux amd64を対象とし、Linuxのビルドはglibc 2.28を基準にします。

配布フォルダは`fest`実行ファイル・`runtime/`・`notices/`です。アーカイブ・SHA-256・対応ソースを一緒に配布します。
署名・公証は未設定です。

公開前にライセンス・対応ソース・展開後の起動・AAC/Opusのデコード・終了時の子プロセス回収を確認します。
ログイン・実機での音声出力は別途確認します。
復旧時は全festを終了し、保存形式に対応するアプリ一式へ戻します。
