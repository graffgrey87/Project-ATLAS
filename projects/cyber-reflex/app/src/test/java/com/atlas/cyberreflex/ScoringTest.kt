package com.atlas.cyberreflex

import android.content.Intent
import android.os.Looper
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLooper

@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class ScoringTest {

    @Test
    fun testScoreIncrementsOnCorrectSequence() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvScore = activity.findViewById<TextView>(R.id.tvScore)
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)

                // Wait for sequence to be shown (novice: showTime=1000, speed=800, 1 cell)
                // Sequence: 1000 + 800 = 1800ms, then "Повторите!"
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(3000)

                // After sequence, player should be able to click
                // First cell in sequence
                val firstCell = grid.getChildAt(0) as Button
                firstCell.performClick()

                // Wait for score update
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(1000)

                // Score should be 10 (10 * combo 1)
                assert(tvScore.text.toString().contains("10"))
            }
        }
    }

    @Test
    fun testComboIncrementsOnCorrectSequence() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvCombo = activity.findViewById<TextView>(R.id.tvCombo)
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)

                // Wait for sequence
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(3000)

                // Click correct cell
                val firstCell = grid.getChildAt(0) as Button
                firstCell.performClick()

                // Wait for combo update
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(1000)

                // Combo should be 1
                assert(tvCombo.text.toString().contains("1"))
            }
        }
    }

    @Test
    fun testGameOverOverlayAppears() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val overlay = activity.findViewById<android.view.View>(R.id.overlay)
                val tvGameOverScore = activity.findViewById<TextView>(R.id.tvGameOverScore)

                // Wait for sequence and then wrong click
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(3000)

                // Click wrong cell (index 1 when sequence is 0)
                val wrongCell = activity.findViewById<android.widget.GridLayout>(R.id.grid).getChildAt(1) as Button
                wrongCell.performClick()

                // Wait for game over (1000ms delay)
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(2000)

                // Overlay should be visible
                assert(overlay.visibility == android.view.View.VISIBLE)
                // Score should be displayed
                assert(tvGameOverScore.text.toString().contains("0"))
            }
        }
    }

    @Test
    fun testScoresSavedToSharedPreferences() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)

                // Wait for sequence
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(3000)

                // Click wrong cell to trigger game over
                val wrongCell = grid.getChildAt(1) as Button
                wrongCell.performClick()

                // Wait for game over
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(2000)

                // Check SharedPreferences
                val prefs = activity.getSharedPreferences("cyberreflex", android.content.Context.MODE_PRIVATE)
                val bestReflex = prefs.getInt("best_reflex", 0)
                // Score is 0 because wrong click happened before any correct sequence
                assert(bestReflex == 0)
            }
        }
    }

    @Test
    fun testRestartGameResetsScore() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvScore = activity.findViewById<TextView>(R.id.tvScore)

                // Wait for sequence
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(3000)

                // Click wrong cell
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)
                val wrongCell = grid.getChildAt(1) as Button
                wrongCell.performClick()

                // Wait for game over
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(2000)

                // Click restart
                val btnRestart = activity.findViewById<Button>(R.id.btnRestart)
                btnRestart.performClick()

                // Wait for restart
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(1000)

                // Score should be reset to 0
                assert(tvScore.text.toString().contains("0"))
            }
        }
    }
}
