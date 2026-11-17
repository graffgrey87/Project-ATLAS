package com.atlas.cyberreflex

import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
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
    private lateinit var overlay: View
    private lateinit var tvGameOverScore: TextView
    private lateinit var btnRestart: MaterialButton
    private lateinit var btnMenu: MaterialButton

    var mode = "reflex"
        private set
    var diff = "novice"
        private set
    var score = 0
        private set
    var combo = 0
        private set
    var gameActive = false
        private set

    private var round = 0
    private var handler = Handler(Looper.getMainLooper())
    private var highlightHandler = Handler(Looper.getMainLooper())
    private var cells = arrayOfNulls<Button>(16)
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
        overlay = findViewById(R.id.overlay)
        tvGameOverScore = findViewById(R.id.tvGameOverScore)
        btnRestart = findViewById(R.id.btnRestart)
        btnMenu = findViewById(R.id.btnMenu)

        btnBack.setOnClickListener { finish() }
        btnRestart.setOnClickListener { restartGame() }
        btnMenu.setOnClickListener { finish() }

        setupGrid()
        startGame()
    }

    private fun cleanupHandlers() {
        handler.removeCallbacksAndMessages(null)
        highlightHandler.removeCallbacksAndMessages(null)
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
        sequence.clear()
        playerSeq.clear()
        gameActive = true
        overlay.visibility = View.GONE
        updateUI()
        nextRound()
    }

    private fun restartGame() {
        cleanupHandlers()
        startGame()
    }

    private fun nextRound() {
        if (!gameActive) return
        val maxRounds = diffConfig[diff]!!["rounds"] as Int
        if (currentRound >= maxRounds) {
            tvMessage.text = getString(R.string.msg_win)
            gameActive = false
            handler.postDelayed({ endGame() }, 1000)
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

        fun showNext() {
            if (!gameActive || i >= sequence.size) {
                isShowingSequence = false
                if (gameActive) tvMessage.text = getString(R.string.msg_repeat)
                return
            }
            highlightCell(sequence[i])
            i++
            handler.postDelayed({ showNext() }, speed.toLong())
        }
        handler.postDelayed({ showNext() }, speed.toLong())
    }

    private fun highlightCell(index: Int) {
        cells[index]?.let {
            it.setBackgroundColor(resources.getColor(R.color.cell_active, theme))
            highlightHandler.postDelayed({
                if (gameActive) {
                    it.setBackgroundColor(resources.getColor(R.color.cell_inactive, theme))
                }
            }, 400)
        }
    }

    private fun onCellClick(index: Int) {
        if (!gameActive || isShowingSequence) return

        highlightCell(index)
        playerSeq.add(index)

        val expectedIndex = playerSeq.size - 1
        if (playerSeq[expectedIndex] != sequence[expectedIndex]) {
            cells[index]?.setBackgroundColor(resources.getColor(R.color.cell_wrong, theme))
            tvMessage.text = getString(R.string.msg_wrong)
            combo = 0
            Toast.makeText(this, getString(R.string.msg_wrong), Toast.LENGTH_SHORT).show()
            gameActive = false
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
        gameActive = false
        cleanupHandlers()

        val prefs = getSharedPreferences("cyberreflex", MODE_PRIVATE)
        if (mode == "reflex") {
            val best = prefs.getInt("best_reflex", 0)
            if (score > best) prefs.edit().putInt("best_reflex", score).apply()
        } else {
            val best = prefs.getInt("best_matrix", 0)
            if (score > best) prefs.edit().putInt("best_matrix", score).apply()
        }

        tvGameOverScore.text = getString(R.string.game_over_score, score)
        overlay.visibility = View.VISIBLE
    }

    override fun onDestroy() {
        super.onDestroy()
        cleanupHandlers()
    }
}
