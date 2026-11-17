package com.atlas.cyberreflex

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.GridLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton

class GameActivity : AppCompatActivity() {
    private lateinit var grid: GridLayout
    private lateinit var tvScore: TextView
    private lateinit var tvCombo: TextView
    private lateinit var tvTimer: TextView
    private lateinit var tvMessage: TextView
    private lateinit var btnBack: MaterialButton

    private var mode = "reflex"
    private var diff = "novice"
    private var score = 0
    private var combo = 0
    private var round = 0
    private var timeLeft = 0
    private var handler = Handler(Looper.getMainLooper())
    private var timerRunnable: Runnable? = null
    private var cells = arrayOfNulls<Button>(9)
    private var sequence = mutableListOf<Int>()
    private var playerSeq = mutableListOf<Int>()
    private var isShowingSequence = false
    private var currentRound = 0

    private val diffConfig = mapOf(
        "novice" to mapOf("roundTime" to 15, "rounds" to 5, "gridSize" to 3, "showTime" to 1000, "speed" to 800),
        "pro" to mapOf("roundTime" to 10, "rounds" to 8, "gridSize" to 3, "showTime" to 700, "speed" to 500),
        "cyber" to mapOf("roundTime" to 8, "rounds" to 12, "gridSize" to 4, "showTime" to 500, "speed" to 300)
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_game)

        mode = intent.getStringExtra("mode") ?: "reflex"
        diff = intent.getStringExtra("diff") ?: "novice"

        grid = findViewById(R.id.grid)
        tvScore = findViewById(R.id.tvScore)
        tvCombo = findViewById(R.id.tvCombo)
        tvTimer = findViewById(R.id.tvTimer)
        tvMessage = findViewById(R.id.tvMessage)
        btnBack = findViewById(R.id.btnBack)

        btnBack.setOnClickListener { finish() }

        setupGrid()
        startGame()
    }

    private fun setupGrid() {
        grid.removeAllViews()
        val size = (diffConfig[diff]!!["gridSize"] as Int).toInt()
        grid.columnCount = size
        grid.rowCount = size

        for (i in 0 until size * size) {
            val btn = Button(this).apply {
                text = ""
                textSize = 24f
                setTextColor(Color.WHITE)
                setBackgroundColor(resources.getColor(R.color.cell_inactive, theme))
                layoutParams = GridLayout.LayoutParams().apply {
                    width = 0
                    height = 0
                    columnSpec = GridLayout.spec(i % size, 1f)
                    rowSpec = GridLayout.spec(i / size, 1f)
                    setMargins(8, 8, 8, 8)
                }
                setOnClickListener { onCellClick(i) }
            }
            grid.addView(btn)
            cells[i] = btn
        }
    }

    private fun startGame() {
        score = 0
        combo = 0
        currentRound = 0
        round = 0
        updateUI()
        nextRound()
    }

    private fun nextRound() {
        val maxRounds = diffConfig[diff]!!["rounds"] as Int
        if (currentRound >= maxRounds) {
            endGame()
            return
        }
        currentRound++
        round = currentRound
        playerSeq.clear()
        sequence.add((0 until cells.size).random())
        showSequence()
    }

    private fun showSequence() {
        isShowingSequence = true
        tvMessage.text = getString(R.string.msg_watch)
        val speed = diffConfig[diff]!!["showTime"] as Int
        var i = 0
        val showHandler = object : Handler(Looper.getMainLooper()) {
            override fun handleMessage(msg: android.os.Message) {
                if (i < sequence.size) {
                    highlightCell(sequence[i])
                    i++
                    if (i < sequence.size) {
                        sendEmptyMessageDelayed(0, speed.toLong())
                    } else {
                        handler.postDelayed({
                            isShowingSequence = false
                            tvMessage.text = getString(R.string.msg_repeat)
                        }, speed.toLong())
                    }
                }
            }
        }
        showHandler.sendEmptyMessageDelayed(0, speed.toLong())
    }

    private fun highlightCell(index: Int) {
        cells[index]?.let {
            it.setBackgroundColor(resources.getColor(R.color.cell_active, theme))
            handler.postDelayed({
                it.setBackgroundColor(resources.getColor(R.color.cell_inactive, theme))
            }, 400)
        }
    }

    private fun onCellClick(index: Int) {
        if (isShowingSequence) return

        highlightCell(index)
        playerSeq.add(index)

        val expectedIndex = playerSeq.size - 1
        if (playerSeq[expectedIndex] != sequence[expectedIndex]) {
            tvMessage.text = getString(R.string.msg_wrong)
            combo = 0
            Toast.makeText(this, getString(R.string.msg_wrong), Toast.LENGTH_SHORT).show()
            handler.postDelayed({ endGame() }, 1000)
            return
        }

        if (playerSeq.size == sequence.size) {
            combo++
            score += 10 * combo
            updateUI()
            handler.postDelayed({ nextRound() }, 500)
        }
    }

    private fun updateUI() {
        tvScore.text = getString(R.string.score, score)
        tvCombo.text = getString(R.string.combo, combo)
        tvTimer.text = getString(R.string.round, round)
    }

    private fun endGame() {
        timerRunnable?.let { handler.removeCallbacks(it) }
        handler.removeCallbacksAndMessages(null)

        val prefs = getSharedPreferences("cyberreflex", MODE_PRIVATE)
        val bestReflex = prefs.getInt("best_reflex", 0)
        val bestMatrix = prefs.getInt("best_matrix", 0)

        if (mode == "reflex" && score > bestReflex) {
            prefs.edit().putInt("best_reflex", score).apply()
        } else if (mode == "matrix" && score > bestMatrix) {
            prefs.edit().putInt("best_matrix", score).apply()
        }

        setContentView(R.layout.activity_game_over)
        findViewById<TextView>(R.id.tvGameOverScore).text =
            getString(R.string.game_over_score, score)
        findViewById<MaterialButton>(R.id.btnRestart).setOnClickListener {
            setContentView(R.layout.activity_game)
            setupGrid()
            startGame()
        }
        findViewById<MaterialButton>(R.id.btnMenu).setOnClickListener {
            finish()
        }
    }
}
