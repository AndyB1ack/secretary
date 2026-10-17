package com.mira.secretary

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Log
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.OfflineTtsConfig
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * Собственный нейроголос Миры (sherpa-onnx + Piper VITS), полностью офлайн.
 * Синтез следующей фразы идёт, пока звучит предыдущая.
 * Модель лежит в files/voice/ (кладёт build_and_install.sh), если её нет — Мира говорит системным голосом.
 */
class MiraVoice private constructor(private val tts: OfflineTts) {
    private val synth = Executors.newSingleThreadExecutor()
    private val player = Executors.newSingleThreadExecutor()
    private val epoch = AtomicInteger(0)
    private val track: AudioTrack = AudioTrack.Builder()
        .setAudioAttributes(AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ASSISTANT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
        .setAudioFormat(AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
            .setSampleRate(tts.sampleRate())
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
        .setTransferMode(AudioTrack.MODE_STREAM)
        .setBufferSizeInBytes(AudioTrack.getMinBufferSize(tts.sampleRate(),
            AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT) * 4)
        .build().apply { play() }

    fun say(text: String) {
        val my = epoch.get()
        synth.execute {
            if (my != epoch.get()) return@execute
            val t0 = System.currentTimeMillis()
            val audio = tts.generate(text, 0, SPEED)
            Log.i(TAG, "TIMING voice=${System.currentTimeMillis() - t0}ms audio=${audio.samples.size * 1000 / audio.sampleRate}ms")
            player.execute {
                if (my != epoch.get()) return@execute
                var off = 0
                val s = audio.samples
                while (off < s.size && my == epoch.get()) {
                    val n = minOf(4096, s.size - off)
                    track.write(s, off, n, AudioTrack.WRITE_BLOCKING)
                    off += n
                }
            }
        }
    }

    /** Замолчать сразу (перебили или новый вопрос). */
    fun stop() {
        epoch.incrementAndGet()
        track.pause(); track.flush(); track.play()
    }

    fun release() {
        stop()
        synth.shutdownNow(); player.shutdownNow()
        track.release(); tts.release()
    }

    companion object {
        private const val TAG = "Mira"
        private const val SPEED = 1.0f

        /** Ищет в папке модель Piper (*.onnx + tokens.txt + espeak-ng-data). */
        fun load(dir: File): MiraVoice? {
            val onnx = dir.listFiles { f -> f.name.endsWith(".onnx") }?.firstOrNull() ?: return null
            return try {
                val t0 = System.currentTimeMillis()
                val cfg = OfflineTtsConfig(
                    model = OfflineTtsModelConfig(
                        vits = OfflineTtsVitsModelConfig(
                            model = onnx.absolutePath,
                            tokens = File(dir, "tokens.txt").absolutePath,
                            dataDir = File(dir, "espeak-ng-data").absolutePath,
                        ),
                        numThreads = 2,
                    ),
                )
                MiraVoice(OfflineTts(config = cfg)).also {
                    Log.i(TAG, "TIMING voice_load=${System.currentTimeMillis() - t0}ms model=${onnx.name}")
                }
            } catch (e: Throwable) {
                Log.e(TAG, "Нейроголос не загрузился, будет системный", e)
                null
            }
        }
    }
}
