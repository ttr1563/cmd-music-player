# Windows版

Windows x64向けのネイティブ版を準備しています。WSLは不要です。
Windows TerminalのPowerShellから起動し、WASAPIで音声を出す設計です。
ARM版WindowsとWSL内での動作は未検証です。

**現在はバイナリ未配布・Windowsでの動作未検証です。**
以下は配布開始後の手順です。Python・uv・Denoの追加インストールは不要です。

## 起動する

リリースからWindows x64版のZIPと同名の`.sha256`をダウンロードします。
PowerShellで、ファイル名を実際の配布ファイル名に置き換えて実行してください。

```console
$archive = "$HOME\Downloads\fest-0.3.0-win32-x86_64.zip"
$expected = ((Get-Content -LiteralPath "$archive.sha256" -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $expected) { throw 'Checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath "$HOME\fest-0.3.0"
& "$HOME\fest-0.3.0\fest\fest.exe" doctor
& "$HOME\fest-0.3.0\fest\fest.exe"
```

展開先に同名フォルダーがある場合は、別の空の場所へ展開してください。
`fest.exe`だけを移動せず、隣の`_internal`も含めてフォルダー全体を保持します。

今のPowerShellから`fest`で起動するには、次を実行します。
新しいターミナルでも使う場合は、Windowsの「環境変数」から同じフォルダーを
ユーザーのPathに追加してください。

```console
$env:Path = "$HOME\fest-0.3.0\fest;$env:Path"
fest
```

## 更新・削除

更新時はfestを終了し、新しい版を別フォルダーへ展開してPathを切り替えます。
設定・暗号化した認証情報は`%LOCALAPPDATA%\music-cli`に保存し、
Windowsの資格情報マネージャーは使いません。

すべて削除する場合は、終了後に`fest purge`を実行し、展開フォルダーと
自分で追加したPathを削除してください。設定を残す場合はpurgeを省略します。
旧フォルダーを保持しておけば、Pathを戻して以前の版を起動できます。
