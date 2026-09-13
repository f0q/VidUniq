#!/usr/bin/env bash
# Скачивает статические ffmpeg + ffprobe для macOS arm64 в vendor/ffmpeg/.
# Источник: https://ffmpeg.martin-riedl.de (статические сборки с libx264 и VideoToolbox).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/ffmpeg"
ARCH="${FFMPEG_ARCH:-arm64}"          # arm64 | amd64
CHANNEL="${FFMPEG_CHANNEL:-release}"  # release | snapshot
BASE="https://ffmpeg.martin-riedl.de/redirect/latest/macos/${ARCH}/${CHANNEL}"

mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for tool in ffmpeg ffprobe; do
  if [[ -x "$DEST/$tool" && "${FORCE:-0}" != "1" ]]; then
    echo "• $tool уже есть: $DEST/$tool (FORCE=1 для перезакачки)"
    continue
  fi
  echo "• Скачиваю $tool ($ARCH, $CHANNEL)…"
  url="$(curl -fL --retry 3 -o "$TMP/$tool.zip" -w '%{url_effective}' "$BASE/$tool.zip")"
  curl -fsL --retry 3 -o "$TMP/$tool.zip.sha256" "${url}.sha256" || true
  if [[ -s "$TMP/$tool.zip.sha256" ]]; then
    expected="$(awk '{print $1}' "$TMP/$tool.zip.sha256")"
    actual="$(shasum -a 256 "$TMP/$tool.zip" | awk '{print $1}')"
    [[ "$expected" == "$actual" ]] || { echo "✗ sha256 не совпал для $tool"; exit 1; }
  fi
  unzip -oq "$TMP/$tool.zip" -d "$TMP/$tool"
  bin="$(find "$TMP/$tool" -type f -name "$tool" | head -1)"
  [[ -n "$bin" ]] || { echo "✗ в архиве нет $tool"; exit 1; }
  install -m 755 "$bin" "$DEST/$tool"
  xattr -d com.apple.quarantine "$DEST/$tool" 2>/dev/null || true
done

echo "• Проверка:"
"$DEST/ffmpeg" -version | head -1
"$DEST/ffprobe" -version | head -1
enc="$("$DEST/ffmpeg" -hide_banner -encoders 2>/dev/null)"
for e in libx264 h264_videotoolbox aac; do
  if grep -q " $e " <<<"$enc"; then echo "  ✓ $e"; else echo "  ✗ $e отсутствует"; fi
done
echo "Готово: $DEST"
