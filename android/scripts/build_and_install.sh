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

SHERPA_VER=1.13.8
VOICE=vits-piper-ru_RU-irina-medium
mkdir -p app/libs
[ -f app/libs/sherpa-onnx.aar ] || { echo "== Скачиваю движок голоса sherpa-onnx $SHERPA_VER (50 МБ)";
  curl -fL -o app/libs/sherpa-onnx.aar https://github.com/k2-fsa/sherpa-onnx/releases/download/v$SHERPA_VER/sherpa-onnx-$SHERPA_VER.aar; }
mkdir -p "$ROOT/models/voice"
[ -d "$ROOT/models/voice/$VOICE" ] || { echo "== Скачиваю голос $VOICE (~65 МБ)";
  curl -fL https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/$VOICE.tar.bz2 | tar xj -C "$ROOT/models/voice"; }

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
if ! "$ADB" shell "[ -f $APPDIR/voice/tokens.txt ]"; then
  echo "== Копирую голос на телефон"
  "$ADB" shell rm -rf $APPDIR/voice
  "$ADB" push "$ROOT/models/voice/$VOICE" $APPDIR/voice > /dev/null
fi
"$ADB" shell am force-stop $PKG
"$ADB" shell am start -n $PKG/.MainActivity
echo "✓ Мира запущена на телефоне"
