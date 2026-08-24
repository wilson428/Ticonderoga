#!/usr/bin/env bash
set -euo pipefail
SRC="data/scans"
DST="data/ocr"
mkdir -p "$DST"

# tweak --rotate-pages, --deskew as needed; add --jobs N for parallel
for inpdf in "$SRC"/*.pdf; do
  base=$(basename "$inpdf")
  outpdf="$DST/$base"
ocrmypdf \
  --force-ocr \
  --rotate-pages --deskew \
  --language eng \
  --optimize 3 \
  --output-type pdf \
  --clean --clean-final \
  --unpaper-args "--pre-wipe 0,10,0,12 --post-wipe 0,10,0,12" \
  "$inpdf" "$outpdf"
done