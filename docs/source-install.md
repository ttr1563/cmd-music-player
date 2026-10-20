# ソースからのビルド

Go 1.27以降を使用します。

アプリ本体をビルドするには、リポジトリのルートで実行します。

```console
CGO_ENABLED=0 go build -trimpath -o fest ./cmd/fest
./fest --help
```

再生には同梱decoderも必要です。完全な配布フォルダを作る場合は、対象OS上で次を実行します。
Cコンパイラ、make、tarが必要です。Linuxではpatchelf、WindowsではVisual Studio C++とMSYS2を使用します。
MSYS2では`pacman -S make`でmakeを導入します。

```console
go run ./cmd/fest-build
```

FFmpegの対応ソースとSHA-256を確認し、GPL・nonfreeの部品を無効にしてビルドします。出力は`dist/`以下です。
利用するPCには展開した`fest`フォルダ一式を配置します。アプリだけを移動しないでください。

Linux版はPulseAudioまたはPipeWireのPulseAudio互換サービスを使用します。
各OSの実機でのログイン・音声出力は、ビルド成功とは別に確認が必要です。
