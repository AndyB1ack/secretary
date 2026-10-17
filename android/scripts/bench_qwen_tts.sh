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

for TALKER in $(echo $FILES | tr ' ' '\n' | grep -i talker); do
  Q=$(echo $TALKER | grep -o 'Q[0-9]_[A-Z0-9_]*' | head -1)
  echo "== $TALKER"
  T0=$(date +%s)
  "$ADB" shell "cd $DEV && ./qwen-tts --model $TALKER --codec $CODEC --speaker serena --lang Russian \
     --instruct 'happy, cheerful, young woman' -o out_$Q.wav < prompt.txt" 2>&1 | tail -3 || true
  T1=$(date +%s)
  "$ADB" pull $DEV/out_$Q.wav voice_samples/phone_qwen_$Q.wav > /dev/null 2>&1 || { echo "   нет звука"; continue; }
  python3 - "voice_samples/phone_qwen_$Q.wav" $((T1 - T0)) <<'PY'
import sys, wave
w = wave.open(sys.argv[1]); dur = w.getnframes() / w.getframerate(); took = int(sys.argv[2])
print(f"   звук {dur:.1f} с, синтез {took} с → RTF {took / dur:.2f} ({'быстрее' if took < dur else 'медленнее'} реального времени)")
PY
done
open voice_samples 2>/dev/null || true
