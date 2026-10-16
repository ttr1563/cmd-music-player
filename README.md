# fest

ターミナルでYouTube Musicを検索・選曲して、音声を再生する非公式プレイヤーです。

**試用版です。Mac・Windows版バイナリは準備中で、実機動作は未確認です。**
[ソースから試す手順](docs/source-install.md)を用意しています。

以下はバイナリ配布開始後の手順です。

## インストール（Mac）

お使いのMac向けの配布ファイル、同名の`.sha256`、`install.sh`をダウンロードします。
追加の実行環境をインストールする必要はありません。

| Mac | 配布ファイル |
| --- | --- |
| Apple Silicon（M1以降） | `fest-0.4.0-darwin-arm64.tar.gz` |
| Intel | `fest-0.4.0-darwin-x86_64.tar.gz` |

3つのファイルをダウンロードフォルダに置き、ターミナルで実行します。

Intelの場合: ファイル名の`arm64`を`x86_64`に変更してください。

```console
sh "$HOME/Downloads/install.sh" "$HOME/Downloads/fest-0.4.0-darwin-arm64.tar.gz"
export PATH="$HOME/.local/bin:$PATH"
fest
```

新しいターミナルで`fest`が見つからない場合は、上の`export PATH=…`を再実行してください。

## Windows

WSLを使わず、Windows上で動く`fest.exe`を準備しています。
[Windows版の手順と対応状況](docs/windows.md)を参照してください。

## 使い方

- 検索欄に曲名やアーティストを入力し、Enterで検索。
- 結果を選んでEnterで再生。
- 画面のボタンで一時停止・次の曲・音量などを操作。
- Ctrl+Qで終了。再生も停止します。

ウィンドウを最小化しても再生は続きます。

## ログイン・アカウント切り替え

自分のライブラリやプレイリストを使う場合は、ログインします。

```console
fest login personal
fest account
```

[ログイン手順](docs/usage.md#初回ログインとアカウント選択)に従って認証してください。
認証情報は暗号化して保存し、Keychainは使いません。

## 更新・削除

更新はfestを終了してから、新しい配布ファイルを同じ手順でインストールします。
設定と認証情報は引き継がれます。

保存データを削除するには、festを終了してから`fest purge`を実行します。
アプリ本体の削除は[アンインストール手順](docs/usage.md#データ削除アンインストール)を参照してください。

困ったときは`fest doctor`で状態を確認できます。

[詳しい使い方](docs/usage.md)
