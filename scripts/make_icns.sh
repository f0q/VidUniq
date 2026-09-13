#!/usr/bin/env bash
# viduniq/resources/icon.png → viduniq/resources/icon.icns (sips + iconutil, только macOS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/viduniq/resources/icon.png"
OUT="$ROOT/viduniq/resources/icon.icns"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
SET="$TMP/icon.iconset"; mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); sips -z $d $d "$SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$OUT"
echo "→ $OUT"
