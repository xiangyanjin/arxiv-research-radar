#!/bin/sh
set -eu
cd "$(dirname "$0")"
radar_python="${ARXIV_RADAR_PYTHON:-python3}"
if ! command -v "$radar_python" >/dev/null 2>&1; then
  printf '%s\n' "Python 3.10+ is required. Set ARXIV_RADAR_PYTHON to its executable." >&2
  exit 1
fi
"$radar_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required.")'
if [ "$#" -eq 0 ]; then set -- serve; fi
exec "$radar_python" -m radar "$@"
