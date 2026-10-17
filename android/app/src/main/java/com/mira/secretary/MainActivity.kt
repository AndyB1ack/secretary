package com.mira.secretary

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.util.Log
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import com.google.android.material.floatingactionbutton.FloatingActionButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale
import java.util.UUID

/**
 * Скелет Миры на телефоне: llama.cpp (Gemma) + системное распознавание и синтез речи Android.
 * Модель кладётся адб-командой в /sdcard/Android/data/com.mira.secretary/files/model.gguf
 * Характер Миры — assets/system_prompt.txt (собирается из persona/mira.yaml скриптом tools/export_prompt.py).
 * Кнопка: есть текст — отправить; пусто — слушать голос.
 */
class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var statusTv: TextView
    private lateinit var messagesRv: RecyclerView
    private lateinit var inputEt: EditText
    private lateinit var fab: FloatingActionButton

    private lateinit var engine: InferenceEngine
    private var generationJob: Job? = null
    private var ready = false

    private val messages = mutableListOf<Message>()
    private val adapter = MessageAdapter(messages)
    private val answer = StringBuilder()

    private lateinit var tts: TextToSpeech

    @Volatile private var voice: MiraVoice? = null
    private var ttsReady = false
    private val sentenceBuf = StringBuilder()
    private var recognizer: SpeechRecognizer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)
        statusTv = findViewById(R.id.gguf)
        messagesRv = findViewById(R.id.messages)
        messagesRv.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        messagesRv.adapter = adapter
        inputEt = findViewById(R.id.user_input)
        fab = findViewById(R.id.fab)
        fab.setImageResource(R.drawable.outline_send_24)
        fab.isEnabled = false
        inputEt.isEnabled = false

        tts = TextToSpeech(this, this)
        lifecycleScope.launch(Dispatchers.IO) {
            voice = MiraVoice.load(File(getExternalFilesDir(null), "voice"))
        }
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS, Manifest.permission.RECORD_AUDIO), 2)
        }
        startForegroundService(Intent(this, MiraService::class.java))
        fab.setOnClickListener {
            if (!ready) return@setOnClickListener
            val text = inputEt.text.toString().trim()
            if (text.isNotEmpty()) send(text) else listen()
        }
        lifecycleScope.launch(Dispatchers.Default) {
            engine = AiChat.getInferenceEngine(applicationContext)
            startMira()
        }
    }

    private suspend fun status(text: String) = withContext(Dispatchers.Main) { statusTv.text = text }

    private suspend fun startMira() {
        val model = File(getExternalFilesDir(null), MODEL_FILE)
        if (!model.exists()) {
            status("Нет модели. Положи её командой:\nadb push model.gguf ${model.path}")
            return
        }
        val t0 = System.currentTimeMillis()
        status("Загружаю модель…")
        engine.loadModel(model.path)
        status("Мира читает свой характер… (первый раз до минуты)")
        val prompt = assets.open(PROMPT_ASSET).bufferedReader().use { it.readText() }
        val tLoad = System.currentTimeMillis() - t0
        engine.setSystemPrompt(prompt)
        val sec = (System.currentTimeMillis() - t0) / 1000
        Log.i(TAG, "TIMING load_model=${tLoad}ms system_prompt=${System.currentTimeMillis() - t0 - tLoad}ms chars=${prompt.length}")
        withContext(Dispatchers.Main) {
            ready = true
            fab.isEnabled = true
            inputEt.isEnabled = true
            inputEt.hint = "Напиши или нажми кнопку и говори"
            statusTv.text = "Мира готова (запуск $sec с). Офлайн."
        }
    }

    private fun send(text: String) {
        inputEt.text = null
        inputEt.isEnabled = false
        fab.isEnabled = false
        tts.stop(); voice?.stop()
        sentenceBuf.clear()
        messages.add(Message(UUID.randomUUID().toString(), text, true))
        answer.clear()
        messages.add(Message(UUID.randomUUID().toString(), "", false))
        adapter.notifyItemRangeInserted(messages.size - 2, 2)
        val t0 = System.currentTimeMillis()
        var first = 0L
        var tokens = 0
        generationJob = lifecycleScope.launch(Dispatchers.Default) {
            engine.sendUserPrompt(text, MAX_TOKENS)
                .onCompletion {
                    withContext(Dispatchers.Main) {
                        flushSpeech(force = true)
                        val total = System.currentTimeMillis() - t0
                        Log.i(TAG, "TIMING first_token=${first}ms total=${total}ms tokens=$tokens " +
                            "gen_speed=${if (total > first) tokens * 1000.0 / (total - first) else 0.0} tok/s")
                        inputEt.isEnabled = true
                        fab.isEnabled = true
                        statusTv.text = "Ответ: первое слово через ${first / 1000.0} с, всего ${(System.currentTimeMillis() - t0) / 1000.0} с"
                    }
                }.collect { token ->
                    if (first == 0L && token.isNotBlank()) first = System.currentTimeMillis() - t0
                    tokens++
                    withContext(Dispatchers.Main) {
                        answer.append(token)
                        messages[messages.size - 1] = messages.last().copy(content = answer.toString().trim())
                        adapter.notifyItemChanged(messages.size - 1)
                        sentenceBuf.append(token)
                        flushSpeech(force = false)
                    }
                }
        }
    }

    /** Озвучиваем по предложениям, пока ответ дописывается. Еврейские буквы голос пропускает — их видно на экране. */
    private fun flushSpeech(force: Boolean) {
        if (!ttsReady && voice == null) return
        val text = sentenceBuf.toString()
        val cut = if (force) text.length else text.indexOfLast { it == '.' || it == '!' || it == '?' || it == '…' } + 1
        if (cut <= 0) return
        val sentence = text.substring(0, cut).replace(HEBREW, "").replace(Regex("[()]"), "").trim()
        sentenceBuf.delete(0, cut)
        if (sentence.length <= 1) return
        val v = voice
        if (v != null) v.say(sentence) else tts.speak(sentence, TextToSpeech.QUEUE_ADD, null, UUID.randomUUID().toString())
    }

    private fun listen() {
        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            Toast.makeText(this, "Распознавание речи недоступно на этом телефоне", Toast.LENGTH_LONG).show()
            return
        }
        tts.stop(); voice?.stop()
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle) {
                    val text = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                    statusTv.text = "Мира готова"
                    if (!text.isNullOrBlank()) send(text)
                }
                override fun onError(error: Int) { statusTv.text = "Не расслышала (код $error). Нажми и скажи ещё раз." }
                override fun onReadyForSpeech(params: Bundle?) { statusTv.text = "Слушаю…" }
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() { statusTv.text = "Думаю…" }
                override fun onPartialResults(partialResults: Bundle?) {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            })
        }
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts.language = Locale("ru", "RU")
            ttsReady = true
        } else {
            Log.w(TAG, "TTS init failed: $status")
        }
    }

    override fun onStop() {
        generationJob?.cancel()
        super.onStop()
    }

    override fun onDestroy() {
        stopService(Intent(this, MiraService::class.java))
        recognizer?.destroy()
        tts.shutdown()
        voice?.release()
        if (::engine.isInitialized) engine.destroy()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "Mira"
        private const val MODEL_FILE = "model.gguf"
        private const val PROMPT_ASSET = "system_prompt.txt"
        private const val MAX_TOKENS = 300
        private val HEBREW = Regex("[\\u0590-\\u05FF]+")
    }
}
