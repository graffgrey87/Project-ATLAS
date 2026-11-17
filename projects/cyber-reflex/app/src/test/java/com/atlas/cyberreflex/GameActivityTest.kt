package com.atlas.cyberreflex

import android.content.Intent
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLooper

@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class GameActivityTest {

    @Test
    fun testGameActivityLaunchesWithReflexMode() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                assert(activity.findViewById<TextView>(R.id.tvScore) != null)
                assert(activity.findViewById<TextView>(R.id.tvCombo) != null)
                assert(activity.findViewById<TextView>(R.id.tvTimer) != null)
                assert(activity.findViewById<TextView>(R.id.tvMessage) != null)
                assert(activity.findViewById<View>(R.id.grid) != null)
            }
        }
    }

    @Test
    fun testGameActivityLaunchesWithMatrixMode() {
        val intent = Intent().apply {
            putExtra("mode", "matrix")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                assert(activity.findViewById<TextView>(R.id.tvScore) != null)
                assert(activity.findViewById<View>(R.id.grid) != null)
            }
        }
    }

    @Test
    fun testGridIs3x3ForNovice() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)
                assert(grid.columnCount == 3)
                assert(grid.rowCount == 3)
                assert(grid.childCount == 9)
            }
        }
    }

    @Test
    fun testGridIs4x4ForCyber() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "cyber")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val grid = activity.findViewById<android.widget.GridLayout>(R.id.grid)
                assert(grid.columnCount == 4)
                assert(grid.rowCount == 4)
                assert(grid.childCount == 16)
            }
        }
    }

    @Test
    fun testBackButtonFinishesActivity() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val btnBack = activity.findViewById<Button>(R.id.btnBack)
                btnBack.performClick()
                assert(scenario.isFinished)
            }
        }
    }

    @Test
    fun testOverlayIsGoneAtStart() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val overlay = activity.findViewById<View>(R.id.overlay)
                assert(overlay.visibility == View.GONE)
            }
        }
    }

    @Test
    fun testScoreDisplaysCorrectly() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvScore = activity.findViewById<TextView>(R.id.tvScore)
                // Score starts at 0
                assert(tvScore.text.toString().contains("0"))
            }
        }
    }

    @Test
    fun testComboDisplaysCorrectly() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvCombo = activity.findViewById<TextView>(R.id.tvCombo)
                // Combo starts at 0
                assert(tvCombo.text.toString().contains("0"))
            }
        }
    }

    @Test
    fun testRoundDisplaysCorrectly() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvTimer = activity.findViewById<TextView>(R.id.tvTimer)
                // Round should display 1 after game starts
                // Give some time for the sequence to show
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(2000)
                assert(tvTimer.text.toString().contains("1"))
            }
        }
    }

    @Test
    fun testMessageShowsWatch() {
        val intent = Intent().apply {
            putExtra("mode", "reflex")
            putExtra("diff", "novice")
        }
        ActivityScenario.launch(GameActivity::class.java, intent).use { scenario ->
            scenario.onActivity { activity ->
                val tvMessage = activity.findViewById<TextView>(R.id.tvMessage)
                // Initially shows "Смотрите!"
                assert(tvMessage.text.toString() == "Смотрите!")
            }
        }
    }
}
