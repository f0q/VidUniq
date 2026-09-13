#!/usr/bin/env bash
# Полная сборка: .app через PyInstaller → ad-hoc подпись → .dmg.
# Требует: uv (или активированный venv с pyinstaller), vendor/ffmpeg (scripts/fetch_ffmpeg.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('viduniq/__init__.py').read()).group(1))")"
ARCH="$(uname -m)"
APP="dist/VidUniq.app"
DMG="dist/VidUniq-${VERSION}-${ARCH}.dmg"
RUN="${PYRUN:-uv run}"

[[ -x vendor/ffmpeg/ffmpeg && -x vendor/ffmpeg/ffprobe ]] || { echo "✗ Нет vendor/ffmpeg — запустите scripts/fetch_ffmpeg.sh"; exit 1; }
[[ -f viduniq/resources/icon.icns ]] || scripts/make_icns.sh

echo "• PyInstaller…"
rm -rf build "$APP" "dist/VidUniq"
$RUN pyinstaller --noconfirm --clean VidUniq.spec

echo "• Удаляю неиспользуемые модули Qt (QML/Quick/Pdf/VirtualKeyboard)…"
FW="$APP/Contents/Frameworks"
for name in QtQml QtQmlMeta QtQmlModels QtQmlWorkerScript QtQuick QtPdf QtVirtualKeyboard QtVirtualKeyboardQml QtOpenGL; do
  rm -rf "$FW/$name" "$FW/PySide6/Qt/lib/$name.framework" "$FW/PySide6/$name.abi3.so" "$FW/PySide6/$name.pyi" \
         "$APP/Contents/Resources/$name" "$APP/Contents/Resources/PySide6/Qt/lib/$name.framework"
done
rm -rf "$FW/PySide6/Qt/plugins/virtualkeyboard" "$FW/PySide6/Qt/plugins/platforminputcontexts" \
       "$FW/PySide6/Qt/plugins/imageformats/libqpdf.dylib" "$FW/PySide6/Qt/plugins/qmltooling" \
       "$FW/PySide6/Qt/qml" "$FW/PySide6/Qt/translations"
find "$APP/Contents/Resources" -type l ! -exec test -e {} \; -delete 2>/dev/null || true

echo "• Ad-hoc подпись (обязательна для arm64)…"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "  ✓ подпись валидна"

echo "• Проверка бандла…"
env -i HOME="$HOME" "$APP/Contents/MacOS/VidUniq" --selftest
[[ -x "$APP/Contents/Frameworks/ffmpeg/ffmpeg" || -x "$APP/Contents/Resources/ffmpeg/ffmpeg" ]] \
  && echo "  ✓ ffmpeg внутри бандла" || { echo "✗ ffmpeg не попал в бандл"; find "$APP" -name ffmpeg -maxdepth 4; exit 1; }

echo "• DMG…"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp scripts/unquarantine.command "$STAGE/Снять карантин.command"
chmod +x "$STAGE/Снять карантин.command"
cat > "$STAGE/ПРОЧТИ.txt" <<TXT
VidUniq ${VERSION} (macOS ${ARCH})

1. Перетащите VidUniq.app в папку Applications.
2. Приложение не подписано сертификатом Apple, поэтому при первом запуске macOS
   покажет предупреждение. Два способа открыть:
   а) Дважды кликните «Снять карантин.command» (после копирования в Applications), или
   б) Системные настройки → Конфиденциальность и безопасность → внизу «Открыть всё равно».
TXT
rm -f "$DMG"
hdiutil create -volname "VidUniq ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO -quiet "$DMG"
echo "✓ $DMG ($(du -h "$DMG" | cut -f1))"
