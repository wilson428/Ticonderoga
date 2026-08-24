#!/usr/bin/env bash
set -euo pipefail

# One-command wrapper around scripts/04_export_part.py
# Usage:
#   ./scripts/publish_part.sh I
#   ./scripts/publish_part.sh II pdf
#   ./scripts/publish_part.sh I pdf --dry-run

PART="${1:-I}"
FORMATS="${2:-pdf}"
shift $(( $# > 0 ? 1 : 0 )) || true
shift $(( $# > 0 ? 1 : 0 )) || true

python3 scripts/04_export_part.py \
  --input "manuscript/believe_in_me.md" \
  --part "$PART" \
  --formats "$FORMATS" \
  --pdf-engine tectonic \
  "$@"
