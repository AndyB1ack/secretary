#!/bin/bash
# Сборка приложения Миры и установка на телефон (USB-отладка включена).
#   bash android/scripts/build_and_install.sh
set -e
cd "$(dirname "$0")/.."
ANDROID_DIR=$(pwd); ROOT=$(dirname "$ANDROID_DIR")
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
ADB="$SDK/platform-tools/adb"
export ANDROID_HOME="$SDK"
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
PKG=com.mira.secretary
APPDIR=/sdcard/Android/data/$PKG/files

echo "sdk.dir=$SDK" > local.properties
[ -d "$SDK/cmake/3.31.6" ] || { echo "== Ставлю CMake 3.31.6"; yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" "cmake;3.31.6" > /dev/null 2>&1 || yes | sdkmanager "cmake;3.31.6"; }
[ -d "$ROOT/native/llama.cpp" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$ROOT/native/llama.cpp"
(cd "$ROOT" && source prototype/.venv/bin/activate 2>/dev/null; python3 tools/export_prompt.py)

echo "== Сборка (первый раз 10–20 минут: Gradle скачает всё нужное)"
./gradlew --no-daemon -q :app:assembleDebug
APK=app/build/outputs/apk/debug/app-debug.apk
ls -lh "$APK"

echo "== Установка на телефон"
"$ADB" install -r "$APK"
"$ADB" shell mkdir -p $APPDIR
if ! "$ADB" shell "[ -f $APPDIR/model.gguf ]"; then
  if "$ADB" shell "[ -f /data/local/tmp/mira/model.gguf ]"; then
    echo "== Переношу модель из теста скорости"
    "$ADB" shell mv /data/local/tmp/mira/model.gguf $APPDIR/model.gguf
  else
    MODEL=$(grep -E '^\s*model:' "$ROOT/prototype/config.yaml" | head -1 | awk '{print $2}')
    "$ADB" push "$ROOT/models/$MODEL" $APPDIR/model.gguf
  fi
fi
"$ADB" shell am start -n $PKG/.MainActivity
echo "✓ Мира запущена на телефоне"
