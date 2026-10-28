#!/usr/bin/env bash
# Keep LF line endings on Windows: see .gitattributes.
set -euo pipefail
exec python3 "$(dirname "${BASH_SOURCE[0]}")/direct_usage.py" "${1:?provider required}"
