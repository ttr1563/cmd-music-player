# 同梱ライブラリ

fest本体はMITライセンスです。Go依存のライセンスとNOTICEは配布物の`notices/go/`に収録します。

FFmpeg 9.0.2はLGPL v2.1以降です。GPL・nonfree・version3の部品を無効にした動的リンク構成を使用します。x264・x265は含めません。
同じリリースの`*.audio-sources.tar.gz`で対応ソースとビルド設定を提供します。FFmpegソースへの変更はありません。

`runtime/`以下のFFmpeg実行ファイル・共有ライブラリは、同じABIの変更版へ交換できます。調査・変更に必要なリバースエンジニアリングを制限しません。
変更版の動作やmacOSの署名状態は利用者側で確認してください。

[FFmpegの配布条件](https://ffmpeg.org/legal.html)
