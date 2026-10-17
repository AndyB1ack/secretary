#!/bin/bash
# Голос Qwen3-TTS на видеокарте телефона через Vulkan — у qwentts.cpp это родной путь для видеокарт
# (все его особые операции, включая кодек, там реализованы; в OpenCL — нет).
# Сначала bench_qwen_tts.sh (исходники и модели), потом:
#   bash android/scripts/bench_qwen_tts_vulkan.sh
set -e
cd "$(dirname "$0")/../.."
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
NDK=$(ls -d "$SDK"/ndk/* | tail -1)
CMAKE_DIR=$(ls -d "$SDK"/cmake/* | tail -1)
CMAKE="$CMAKE_DIR/bin/cmake"; NINJA="$CMAKE_DIR/bin/ninja"
ADB="$SDK/platform-tools/adb"
TC="$NDK/build/cmake/android.toolchain.cmake"
HOST=$(ls "$NDK/toolchains/llvm/prebuilt" | head -1)
SYSROOT="$NDK/toolchains/llvm/prebuilt/$HOST/sysroot"
GLSLC=$(ls "$NDK"/shader-tools/*/glslc | head -1)
VKLIB="$SYSROOT/usr/lib/aarch64-linux-android/28/libvulkan.so"
DEV=/data/local/tmp/qtts
SRC=native/qwentts.cpp
VK=native/vulkan
[ -d $SRC ] || { echo "Сначала запусти android/scripts/bench_qwen_tts.sh"; exit 1; }
"$ADB" devices | sed -n '2p' | grep -q device || { echo "Телефон не виден."; exit 1; }
[ -x "$GLSLC" ] || { echo "Нет glslc в NDK ($NDK/shader-tools)"; exit 1; }
[ -f "$VKLIB" ] || { echo "Нет libvulkan.so в NDK: $VKLIB"; exit 1; }

echo "== Заголовки Vulkan"
[ -d $VK/Vulkan-Headers ] || git clone -q --depth 1 https://github.com/KhronosGroup/Vulkan-Headers $VK/Vulkan-Headers
if [ ! -f $VK/spirv/share/cmake/SPIRV-Headers/SPIRV-HeadersConfig.cmake ]; then
  [ -d $VK/SPIRV-Headers ] || git clone -q --depth 1 https://github.com/KhronosGroup/SPIRV-Headers $VK/SPIRV-Headers
  "$CMAKE" -S $VK/SPIRV-Headers -B $VK/SPIRV-Headers/build -G Ninja -DCMAKE_MAKE_PROGRAM="$NINJA" \
    -DSPIRV_HEADERS_ENABLE_TESTS=OFF -DSPIRV_HEADERS_ENABLE_INSTALL=ON > /dev/null
  "$CMAKE" --install $VK/SPIRV-Headers/build --prefix "$(pwd)/$VK/spirv" > /dev/null
fi

echo "== Сборка голоса с Vulkan (5–15 минут: компилируются шейдеры)"
"$CMAKE" -S $SRC -B native/build-qtts-vulkan -G Ninja -DCMAKE_MAKE_PROGRAM="$NINJA" \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 \
  -DCMAKE_C_FLAGS="-march=armv8.7-a" -DCMAKE_CXX_FLAGS="-march=armv8.7-a" \
  -DGGML_VULKAN=ON -DVulkan_INCLUDE_DIR="$(pwd)/$VK/Vulkan-Headers/include" -DVulkan_LIBRARY="$VKLIB" \
  -DVulkan_GLSLC_EXECUTABLE="$GLSLC" \
  -DSPIRV-Headers_DIR="$(pwd)/$VK/spirv/share/cmake/SPIRV-Headers" \
  -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release > native/vulkan_cmake.log 2>&1 \
  || { tail -30 native/vulkan_cmake.log; exit 1; }
"$CMAKE" --build native/build-qtts-vulkan -j 8 > native/vulkan_build.log 2>&1 || { grep -E "error|Error" native/vulkan_build.log | head -20; exit 1; }
BIN=$(find native/build-qtts-vulkan -type f -name qwen-tts -perm -u+x | head -1)
[ -n "$BIN" ] || { echo "Сборка не удалась"; exit 1; }
"$ADB" push "$BIN" $DEV/qwen-tts-vk > /dev/null && "$ADB" shell chmod +x $DEV/qwen-tts-vk

CODEC=$("$ADB" shell "ls $DEV" | tr -d '\r' | grep -i tokenizer | head -1)
mkdir -p voice_samples
for TALKER in $("$ADB" shell "ls $DEV" | tr -d '\r' | grep -i talker); do
  Q=$(echo $TALKER | grep -o 'Q[0-9]_[A-Z0-9_]*' | head -1)
  echo "== Vulkan, $TALKER"
  "$ADB" shell "cd $DEV && ./qwen-tts-vk --model $TALKER --codec $CODEC --speaker serena --lang Russian \
     --instruct 'slightly happy, warm smile in the voice' -o out_vk_$Q.wav < prompt.txt; echo EXIT=\$?" \
     > voice_samples/vk_log_$Q.txt 2>&1 || true
  grep -E "\[Perf\]|\[Load\]|ggml_vulkan: [0-9]|EXIT|FATAL|not implemented|abort" voice_samples/vk_log_$Q.txt || true
  "$ADB" pull $DEV/out_vk_$Q.wav voice_samples/phone_qwen_vk_$Q.wav > /dev/null 2>&1 || true
done
echo
echo "Журналы: voice_samples/vk_log_*.txt — я их прочитаю сам."
