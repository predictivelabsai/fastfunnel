#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

FRAMES_DIR="docs/demo/frames"
OUT="${OUT:-docs/demo/fastfunnel-walkthrough.gif}"
DELAY="${DELAY:-160}"
WIDTH="${WIDTH:-1100}"

if ! ls "$FRAMES_DIR"/*.png >/dev/null 2>&1; then
  echo "No PNG frames in $FRAMES_DIR. Run scripts/capture_demo.py first." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"

if command -v convert >/dev/null 2>&1; then
  convert -loop 0 -delay "$DELAY" -resize "${WIDTH}x" \
    "$FRAMES_DIR"/*.png -layers Optimize "$OUT"
elif command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -framerate "$(awk "BEGIN{print 100/$DELAY}")" \
    -pattern_type glob -i "$FRAMES_DIR/*.png" \
    -vf "scale=${WIDTH}:-1:flags=lanczos" "$OUT"
else
  echo "ImageMagick or ffmpeg is required." >&2
  exit 1
fi

echo "Wrote $OUT"
