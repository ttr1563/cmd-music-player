#!/bin/sh
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'Mac上で実行してください。' >&2; exit 1; }
cd "$(dirname -- "$0")/.."
exec go run ./cmd/fest-build
