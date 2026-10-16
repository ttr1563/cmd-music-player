#!/bin/sh
# Maintainers only. End users install the generated archive with install.sh.
set -eu

[ "$(uname -s)" = Darwin ] || { echo 'Mac上で実行してください。' >&2; exit 1; }
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/music-macos-build.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT HUP INT TERM
python3 -m venv "$build_dir/tools"
"$build_dir/tools/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: uv==0.13.1
export UV_PROJECT_ENVIRONMENT="$build_dir/env"
export UV_CACHE_DIR="$build_dir/cache"
cd "$project_dir"
"$build_dir/tools/bin/uv" sync --locked --group binary --python 3.12 --no-build-package av --no-build-package miniaudio
"$build_dir/env/bin/python" -m pytest -q --basetemp="$build_dir/pytest"
"$build_dir/env/bin/python" scripts/build_binary.py
case "$(uname -m)" in
    arm64) target=darwin-arm64 ;;
    x86_64) target=darwin-x86_64 ;;
    *) echo '未対応のMac architectureです。' >&2; exit 1 ;;
esac
"$build_dir/env/bin/python" tests/binary_smoke.py "$project_dir/dist/binary-$target/fest/fest"
