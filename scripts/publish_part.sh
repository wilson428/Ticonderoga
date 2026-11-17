#!/usr/bin/env bash
set -euo pipefail

# One-command wrapper around scripts/04_export_part.py
# Usage:
#   ./scripts/publish_part.sh I [pdf] [extra flags]          # one PART
#   ./scripts/publish_part.sh chapters:1-50 [pdf] [flags]     # chapter range (PART headers kept)
#   add --agent-friendly for plain markdown output

SEL="${1:-I}"
FORMATS="${2:-pdf}"
shift $(( $# > 0 ? 1 : 0 )) || true
shift $(( $# > 0 ? 1 : 0 )) || true

if [[ "$SEL" == chapters:* ]]; then
  SELECT=(--chapters "${SEL#chapters:}")
else
  SELECT=(--part "$SEL")
fi

python3 scripts/04_export_part.py \
  --input "manuscripts/believe-in-me/believe_in_me.md" \
  "${SELECT[@]}" \
  --formats "$FORMATS" \
  --pdf-engine tectonic \
  "$@"
