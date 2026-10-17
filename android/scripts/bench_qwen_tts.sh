#!/bin/bash
# Проверка: потянет ли телефон голос Qwen3-TTS (qwentts.cpp, C++/GGML) — без приложения, напрямую через adb.
#   bash android/scripts/bench_qwen_tts.sh
# Результат: wav-файлы в voice_samples/phone_*.wav и коэффициент скорости (RTF < 1 — быстрее реального времени).
set -e
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
NDK=$(ls -d "$SDK"/ndk/* | tail -1)
CMAKE_DIR=$(ls -d "$SDK"/cmake/* | tail -1)
ADB="$SDK/platform-tools/adb"
DEV=/data/local/tmp/qtts
SRC=native/qwentts.cpp
MD=models/qwen-tts
HF=https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF

"$ADB" devices | sed -n '2p' | grep -q device || { echo "Телефон не виден. Разреши отладку и запусти снова."; exit 1; }

echo "== Исходники qwentts.cpp"
[ -d $SRC ] || git clone --recurse-submodules --depth 1 https://github.com/ServeurpersoCom/qwentts.cpp $SRC

# Число потоков: по умолчанию половина ядер (4 на S25) — добавляем переменную QT_THREADS, чтобы подобрать
grep -q QT_THREADS $SRC/src/backend.h || python3 - $SRC/src/backend.h <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("static int backend_cpu_n_threads(void) {\n",
              "static int backend_cpu_n_threads(void) {\n    if (const char * e = std::getenv(\"QT_THREADS\")) { int t = std::atoi(e); if (t > 0) return t; }\n", 1)
if "#include <cstdlib>" not in s: s = "#include <cstdlib>\n" + s
open(p, "w").write(s)
PY

echo "== Сборка под Android (несколько минут)"
"$CMAKE_DIR/bin/cmake" -S $SRC -B native/build-qtts-android -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$CMAKE_DIR/bin/ninja" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 \
  -DCMAKE_C_FLAGS="-march=armv8.7-a" -DCMAKE_CXX_FLAGS="-march=armv8.7-a" \
  -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release > /dev/null
"$CMAKE_DIR/bin/cmake" --build native/build-qtts-android -j 8
BIN=$(find native/build-qtts-android -type f -name qwen-tts -perm -u+x | head -1)
[ -n "$BIN" ] || { echo "Не нашёл собранный qwen-tts"; exit 1; }

echo "== Модели (0.6B CustomVoice: Q4_K_M и Q8_0 + кодек)"
mkdir -p $MD
FILES=$(curl -fsSL https://huggingface.co/api/models/Serveurperso/Qwen3-TTS-GGUF | python3 -c "
import json,sys
names=[s['rfilename'] for s in json.load(sys.stdin)['siblings']]
want=[n for n in names if ('0.6b' in n.lower() and 'customvoice' in n.lower() and ('Q4_K_M' in n or 'Q8_0' in n))
      or ('tokenizer' in n.lower() and 'Q8_0' in n)]
print(' '.join(want))")
echo "   $FILES"
for f in $FILES; do [ -f $MD/$f ] || curl -fL -o $MD/$f "$HF/resolve/main/$f"; done

echo "== На телефон"
"$ADB" shell mkdir -p $DEV
"$ADB" push "$BIN" $DEV/qwen-tts > /dev/null && "$ADB" shell chmod +x $DEV/qwen-tts
for f in $FILES; do "$ADB" shell "[ -f $DEV/$f ]" || "$ADB" push $MD/$f $DEV/ > /dev/null; done
CODEC=$(echo $FILES | tr ' ' '\n' | grep -i tokenizer | head -1)
TEXT="Андрей, по объекту Аргаман всё готово. Завтра в шесть утра бригада на месте. Ну что, договорились?"
"$ADB" shell "echo '$TEXT' > $DEV/prompt.txt"
mkdir -p voice_samples

Q4=$(echo $FILES | tr ' ' '\n' | grep -i talker | grep Q4 | head -1)
for TH in ${THREADS:-4 6 8}; do
  echo "== $Q4, потоков: $TH"
  "$ADB" shell "cd $DEV && QT_THREADS=$TH ./qwen-tts --model $Q4 --codec $CODEC --speaker serena --lang Russian \
     --instruct 'slightly happy, warm smile in the voice' -o out_t$TH.wav < prompt.txt" 2>&1 | grep -E "\[Perf\]|\[Load\].*threads" || true
  "$ADB" pull $DEV/out_t$TH.wav voice_samples/phone_qwen_t$TH.wav > /dev/null 2>&1 || true
done
echo
echo "RTF < 1 — телефон говорит быстрее реального времени. Пришли эти строки [Perf]."
