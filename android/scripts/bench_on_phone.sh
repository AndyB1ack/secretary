#!/bin/bash
# Замер скорости Миры на телефоне: собирает llama.cpp под Android, кладёт модель на телефон и запускает тест.
# Запуск (телефон подключён по USB, отладка включена):  bash android/scripts/bench_on_phone.sh
set -e
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
NDK=$(ls -d "$SDK"/ndk/* | tail -1)
CMAKE_DIR=$(ls -d "$SDK"/cmake/* | tail -1)
ADB="$SDK/platform-tools/adb"
MODEL=$(grep -E '^\s*model:' prototype/config.yaml | head -1 | awk '{print $2}')
DEV=/data/local/tmp/mira

echo "== Телефон"
"$ADB" devices | sed -n '2p' | grep -q device || { echo "Телефон не виден. Разреши отладку на экране телефона и запусти снова."; exit 1; }
"$ADB" shell getprop ro.product.model

echo "== Сборка llama.cpp под Android (первый раз 3–5 минут)"
[ -d native/llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp native/llama.cpp
"$CMAKE_DIR/bin/cmake" -S native/llama.cpp -B native/build-android -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$CMAKE_DIR/bin/ninja" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 \
  -DCMAKE_C_FLAGS="-march=armv8.7-a" -DCMAKE_CXX_FLAGS="-march=armv8.7-a" \
  -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DLLAMA_CURL=OFF -DBUILD_SHARED_LIBS=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF -DCMAKE_BUILD_TYPE=Release > /dev/null
"$CMAKE_DIR/bin/cmake" --build native/build-android --target llama-bench llama-completion -j 8

echo "== Копирую на телефон (модель ~4 ГБ, пару минут)"
"$ADB" shell mkdir -p $DEV
"$ADB" push native/build-android/bin/llama-bench native/build-android/bin/llama-completion $DEV/ > /dev/null
"$ADB" shell "[ -f $DEV/model.gguf ] && [ \$(stat -c %s $DEV/model.gguf) = $(stat -f %z "models/$MODEL") ]" \
  || "$ADB" push "models/$MODEL" $DEV/model.gguf
"$ADB" shell chmod +x $DEV/llama-bench $DEV/llama-completion

echo "== Тест скорости: pp = чтение вопроса, tg = генерация ответа (токенов в секунду)"
"$ADB" shell "cd $DEV && ./llama-bench -m model.gguf -p 256 -n 64 -t 4,6,8 -r 2"

echo "== Живой ответ"
"$ADB" shell "cd $DEV && ./llama-completion -m model.gguf -t 6 -n 60 -p 'Привет! Ты Мира, ассистентка монтажника лифтов. Ответь в двух предложениях: как прошёл твой день?'" 2>/dev/null | tail -5
