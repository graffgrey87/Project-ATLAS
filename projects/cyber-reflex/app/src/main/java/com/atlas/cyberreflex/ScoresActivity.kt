package com.atlas.cyberreflex

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import android.widget.TextView

class ScoresActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_scores)

        val prefs = getSharedPreferences("cyberreflex", MODE_PRIVATE)
        findViewById<TextView>(R.id.tvScoreReflex).text = prefs.getInt("best_reflex", 0).toString()
        findViewById<TextView>(R.id.tvScoreMatrix).text = prefs.getInt("best_matrix", 0).toString()

        findViewById<MaterialButton>(R.id.btnBack).setOnClickListener {
            finish()
        }
    }
}
