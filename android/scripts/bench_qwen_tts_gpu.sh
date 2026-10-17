#!/bin/bash
# Голос Qwen3-TTS на ВИДЕОКАРТЕ телефона (Adreno, OpenCL — бэкенд, который поддерживает сама Qualcomm).
# Сначала запусти bench_qwen_tts.sh (он скачает исходники и модели), потом:
#   bash android/scripts/bench_qwen_tts_gpu.sh
set -e
cd "$(dirname "$0")/../.."
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
NDK=$(ls -d "$SDK"/ndk/* | tail -1)
CMAKE_DIR=$(ls -d "$SDK"/cmake/* | tail -1)
CMAKE="$CMAKE_DIR/bin/cmake"; NINJA="$CMAKE_DIR/bin/ninja"
ADB="$SDK/platform-tools/adb"
TC="$NDK/build/cmake/android.toolchain.cmake"
DEV=/data/local/tmp/qtts
SRC=native/qwentts.cpp
CL=native/opencl
[ -d $SRC ] || { echo "Сначала запусти android/scripts/bench_qwen_tts.sh"; exit 1; }
"$ADB" devices | sed -n '2p' | grep -q device || { echo "Телефон не виден."; exit 1; }

echo "== OpenCL: заголовки и загрузчик под Android"
mkdir -p $CL
[ -d $CL/OpenCL-Headers ] || git clone -q --depth 1 https://github.com/KhronosGroup/OpenCL-Headers $CL/OpenCL-Headers
[ -d $CL/OpenCL-ICD-Loader ] || git clone -q --depth 1 https://github.com/KhronosGroup/OpenCL-ICD-Loader $CL/OpenCL-ICD-Loader
if [ ! -f $CL/build/libOpenCL.so ]; then
  "$CMAKE" -S $CL/OpenCL-ICD-Loader -B $CL/build -G Ninja -DCMAKE_MAKE_PROGRAM="$NINJA" \
    -DCMAKE_TOOLCHAIN_FILE="$TC" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=28 \
    -DOPENCL_ICD_LOADER_HEADERS_DIR="$(pwd)/$CL/OpenCL-Headers" -DCMAKE_BUILD_TYPE=Release > /dev/null
  "$CMAKE" --build $CL/build -j 8 > /dev/null
fi

echo "== Сборка голоса с OpenCL (несколько минут)"
"$CMAKE" -S $SRC -B native/build-qtts-opencl -G Ninja -DCMAKE_MAKE_PROGRAM="$NINJA" \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 \
  -DCMAKE_C_FLAGS="-march=armv8.7-a" -DCMAKE_CXX_FLAGS="-march=armv8.7-a" \
  -DGGML_OPENCL=ON -DGGML_OPENCL_EMBED_KERNELS=ON -DGGML_OPENCL_USE_ADRENO_KERNELS=ON \
  -DOpenCL_INCLUDE_DIR="$(pwd)/$CL/OpenCL-Headers" -DOpenCL_LIBRARY="$(pwd)/$CL/build/libOpenCL.so" \
  -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release > /dev/null
"$CMAKE" --build native/build-qtts-opencl -j 8 2>&1 | tail -2
BIN=$(find native/build-qtts-opencl -type f -name qwen-tts -perm -u+x | head -1)
[ -n "$BIN" ] || { echo "Сборка не удалась"; exit 1; }
"$ADB" push "$BIN" $DEV/qwen-tts-gpu > /dev/null && "$ADB" shell chmod +x $DEV/qwen-tts-gpu

CODEC=$("$ADB" shell "ls $DEV" | tr -d '\r' | grep -i tokenizer | head -1)
mkdir -p voice_samples
for TALKER in $("$ADB" shell "ls $DEV" | tr -d '\r' | grep -i talker); do
  Q=$(echo $TALKER | grep -o 'Q[0-9]_[A-Z0-9_]*' | head -1)
  echo "== Видеокарта, $TALKER"
  "$ADB" shell "cd $DEV && LD_LIBRARY_PATH=/vendor/lib64:/system/vendor/lib64 ./qwen-tts-gpu --model $TALKER \
     --codec $CODEC --speaker serena --lang Russian --instruct 'slightly happy, warm smile in the voice' \
     -o out_gpu_$Q.wav < prompt.txt" 2>&1 | grep -E "\[Perf\]|\[Load\]|rror|not available" || true
  "$ADB" pull $DEV/out_gpu_$Q.wav voice_samples/phone_qwen_gpu_$Q.wav > /dev/null 2>&1 || true
done
echo
echo "Смотри строку «[Load] ... backend:» — там должна быть видеокарта (OpenCL / Adreno), и RTF в «[Perf] Total». Пришли эти строки."
