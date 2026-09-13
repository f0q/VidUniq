#!/bin/bash
# Снимает карантин Gatekeeper с VidUniq.app (приложение не подписано Apple Developer ID).
# Двойной клик по этому файлу → ввод пароля не требуется.
APP="/Applications/VidUniq.app"
[ -d "$APP" ] || APP="$(dirname "$0")/VidUniq.app"
if [ ! -d "$APP" ]; then
  echo "VidUniq.app не найден ни в /Applications, ни рядом с этим скриптом."
  echo "Сначала перетащите VidUniq в Applications."
  read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
fi
xattr -cr "$APP" && echo "Готово: карантин снят с $APP. Теперь приложение открывается двойным кликом."
read -n 1 -s -r -p "Нажмите любую клавишу, чтобы закрыть окно…"
