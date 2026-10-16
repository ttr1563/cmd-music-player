# cmd-music-player

ターミナルでYouTube Musicを検索・選曲して、音声を再生する非公式プレイヤーです。

**試用版です。Macの実機動作は未確認で、Mac版バイナリは準備中。**
[ソースから試す手順](docs/source-install.md)を用意しています。

以下はバイナリ配布開始後の手順です。

## インストール（Mac）

お使いのMac向けの配布ファイル、同名の`.sha256`、`install.sh`をダウンロードします。
追加の実行環境をインストールする必要はありません。

| Mac | 配布ファイル |
| --- | --- |
| Apple Silicon（M1以降） | `music-0.2.0-darwin-arm64.tar.gz` |
| Intel | `music-0.2.0-darwin-x86_64.tar.gz` |

3つのファイルをダウンロードフォルダに置き、ターミナルで実行します。

Intelの場合: ファイル名の`arm64`を`x86_64`に変更してください。

```console
sh "$HOME/Downloads/install.sh" "$HOME/Downloads/music-0.2.0-darwin-arm64.tar.gz"
export PATH="$HOME/.local/bin:$PATH"
music
```

新しいターミナルで`music`が見つからない場合は、上の`export PATH=…`を再実行してください。

## 使い方

- 検索欄に曲名やアーティストを入力し、Enterで検索。
- 結果を選んでEnterで再生。
- 画面のボタンで一時停止・次の曲・音量などを操作。
- Ctrl+Qで終了。再生も停止します。

ウィンドウを最小化しても再生は続きます。

## ログイン・アカウント切り替え

自分のライブラリやプレイリストを使う場合は、ログインします。

```console
music login personal
music account
```

[ログイン手順](docs/usage.md#初回ログインとアカウント選択)に従って認証してください。
認証情報は暗号化して保存し、Keychainは使いません。

## 更新・削除

更新はmusicを終了してから、新しい配布ファイルを同じ手順でインストールします。
設定と認証情報は引き継がれます。

保存データを削除するには、musicを終了してから`music purge`を実行します。
アプリ本体の削除は[アンインストール手順](docs/usage.md#データ削除アンインストール)を参照してください。

困ったときは`music doctor`で状態を確認できます。

[詳しい使い方](docs/usage.md)
