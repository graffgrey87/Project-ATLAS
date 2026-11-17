package com.atlas.cyberreflex

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.GridLayout
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val rgMode = findViewById<RadioGroup>(R.id.rgMode)
        val rgDiff = findViewById<RadioGroup>(R.id.rgDiff)
        val btnStart = findViewById<MaterialButton>(R.id.btnStart)
        val btnScores = findViewById<MaterialButton>(R.id.btnScores)

        btnStart.setOnClickListener {
            val mode = if (rgMode.checkedRadioButtonId == R.id.rbMatrix) "matrix" else "reflex"
            val diff = when (rgDiff.checkedRadioButtonId) {
                R.id.rbNovice -> "novice"
                R.id.rbPro -> "pro"
                R.id.rbCyber -> "cyber"
                else -> "novice"
            }
            val intent = Intent(this, GameActivity::class.java).apply {
                putExtra("mode", mode)
                putExtra("diff", diff)
            }
            startActivity(intent)
        }

        btnScores.setOnClickListener {
            startActivity(Intent(this, ScoresActivity::class.java))
        }
    }
}
