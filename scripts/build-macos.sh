#!/bin/sh
# Compatibility entry point for maintainers; Python 3.12 is required.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'Mac上で実行してください。' >&2; exit 1; }
exec python3 "$(dirname -- "$0")/build_native.py"
