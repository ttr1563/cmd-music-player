# ソースから試す

v0.3.0は開発中のソース試用版です。Mac版バイナリはまだ配布していません。
Macの実機、実アカウントでの再生、実際のスピーカー出力は未確認です。

この導入方法ではuvとDenoが必要です。音楽を聴くMacのターミナルで実行してください。
Homebrewが未導入の場合は[公式の導入手順](https://brew.sh/)を参照してください。

```console
brew install uv deno
uv tool install --python 3.12 --no-build-package av --no-build-package miniaudio 'https://github.com/ttr1563/cmd-music-player/archive/refs/tags/v0.3.0.zip'
uv tool update-shell
```

案内に従ってターミナルを開き直し、起動します。

```console
fest doctor
fest
```

Apple SiliconではmacOS 14以上が必要です。
まず検索を試し、ログインを求められた場合や自分のライブラリを使いたい場合は、
[ログイン手順](usage.md#初回ログインとアカウント選択)へ進んでください。

音が出ない場合は`fest doctor --audio`で出力デバイスを開けるか確認できます。
問題の報告は[Issues](https://github.com/ttr1563/cmd-music-player/issues)へお願いします。
Cookieや認証情報は記載しないでください。

## 旧版から更新する

以前の`music`コマンドで導入していた場合は、上の`uv tool install`に
`--reinstall --refresh`を追加して実行します。更新後の起動コマンドは`fest`です。
認証情報と設定は引き継ぎます。

## 削除

festをすべて終了してから実行します。

```console
fest purge
uv tool uninstall music-cli-local
```

設定と認証情報を残したい場合は`fest purge`を省略してください。
uvやDenoは、他の用途でも使う可能性があるため削除しません。
