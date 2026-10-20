# fest

YouTube Musicをターミナルで検索・選曲・再生する非公式プレイヤーです。

Mac・Linux・Windowsを対象とし、WindowsではWSLを使いません。
追加の実行環境の導入は不要です。

**実アカウントでのログイン・実機の音声出力は未確認です。署名・公証は行っていません。**

## インストール

[リリース](https://github.com/ttr1563/cmd-music-player/releases/tag/v0.4.0)から、OSに合うアーカイブと同名の`.sha256`をダウンロードします。
Macでは同じページの`install.sh`もダウンロードし、ターミナルで実行します。

```console
cd ~/Downloads
sh install.sh fest-0.4.0-darwin-arm64.tar.gz
export PATH="$HOME/.local/bin:$PATH"
fest
```

Intel Macではファイル名の`arm64`を`x86_64`に置き換えてください。
LinuxではSHA-256を照合して展開し、`fest`フォルダー内の`./fest`を起動します。
Windowsの手順は[こちら](docs/windows.md)です。

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
