# fest

YouTube Musicをターミナルで検索・選曲・再生する非公式プレイヤーです。

**配布バイナリはまだ公開していません。**
Mac・Linux・Windowsを対象とし、WindowsではWSLを使いません。
配布版では追加の実行環境の導入は不要です。

## 使い方

```console
fest
fest login personal
fest account
```

曲名を検索してEnterで再生します。Tabで操作を移動し、画面から一時停止・音量・シーク・キューを操作できます。Ctrl+Qで再生も終了します。

認証情報は暗号化ファイルに保存し、Keychainは使いません。

```console
fest doctor
fest config show
fest purge
```

[詳しい使い方](docs/usage.md) · [ソースからのビルド](docs/source-install.md) · [Windows](docs/windows.md)
