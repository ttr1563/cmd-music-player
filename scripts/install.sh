#!/bin/sh
# Install a downloaded Mac archive; no Python, uv or Deno installation needed.
set -eu
umask 077

fail() { echo "music install: $*" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || fail 'Mac用のinstallerです。'
[ "$#" -eq 1 ] || fail '使い方: sh install.sh /path/to/music-0.2.0-darwin-arm64.tar.gz'
case "$(uname -m)" in
    arm64) target=darwin-arm64 ;;
    x86_64) target=darwin-x86_64 ;;
    *) fail '未対応のMac architectureです。' ;;
esac
archive_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
archive="$archive_dir/$(basename -- "$1")"
case "$archive" in
    *-"$target".tar.gz) ;;
    *) fail "このMacには$target用のarchiveが必要です。" ;;
esac
[ -f "$archive" ] && [ -f "$archive.sha256" ] || fail 'archiveと.sha256を同じ場所に置いてください。'
expected=$(awk 'NR == 1 {print $1}' "$archive.sha256")
[ "${#expected}" -eq 64 ] || fail 'SHA256の形式が不正です。'
case "$expected" in *[!a-f0-9]*) fail 'SHA256の形式が不正です。' ;; esac
actual=$(shasum -a 256 "$archive" | awk '{print $1}')
[ "$actual" = "$expected" ] || fail 'SHA256が一致しません。installしていません。'

install_prefix=${MUSIC_INSTALL_PREFIX:-"$HOME/.local"}
install_root="$install_prefix/share/music-cli"
bin_dir="$install_prefix/bin"
[ ! -L "$install_root" ] || fail '保存先がsymlinkです。'
if [ -e "$install_root" ]; then
    [ -f "$install_root/.music-cli-install" ] || fail '保存先はこのinstallerの管理領域ではありません。'
fi
if [ -e "$bin_dir/music" ] || [ -L "$bin_dir/music" ]; then
    [ -L "$bin_dir/music" ] || fail '同名の別コマンドが存在します。'
    case "$(readlink "$bin_dir/music")" in
        "$install_root"/bundles/*/music) ;;
        *) fail '同名の別コマンドが存在します。' ;;
    esac
fi
staging=$(mktemp -d "${TMPDIR:-/tmp}/music-install.XXXXXX")
link_tmp="$bin_dir/.music-install-$$"
trap 'rm -rf -- "$staging"; rm -f -- "$link_tmp"' EXIT HUP INT TERM
tar -tzf "$archive" > "$staging/entries"
awk '/^\// || /(^|\/)\.\.(\/|$)/ || $0 !~ /^music(\/|$)/ {bad=1} END {exit bad}' "$staging/entries" || fail 'archiveのpathが不正です。'
tar -xzf "$archive" -C "$staging"
[ -x "$staging/music/music" ] && [ -d "$staging/music/_internal" ] || fail '配布fileが不足しています。'
case "$target:$(file -b "$staging/music/music")" in
    darwin-arm64:*Mach-O*arm64*|darwin-x86_64:*Mach-O*x86_64*) ;;
    *) fail 'このMac用の実行fileではありません。' ;;
esac
"$staging/music/music" --help > /dev/null
mkdir -p "$install_root/bundles" "$bin_dir"
touch "$install_root/.music-cli-install"
bundle="$install_root/bundles/$actual"
[ ! -e "$bundle" ] || fail '同じ配布物がinstall済みです。'
mv "$staging/music" "$bundle"
ln -s "$bundle/music" "$link_tmp"
mv -f "$link_tmp" "$bin_dir/music"
echo "installしました: $bin_dir/music"
echo 'PATH未設定の場合はterminalで実行: export PATH="$HOME/.local/bin:$PATH"'
echo '起動: music'
