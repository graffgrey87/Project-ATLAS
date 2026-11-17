package com.atlas.cyberreflex

import android.content.Intent
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class ScoresActivityTest {

    @Test
    fun testScoresActivityLaunches() {
        ActivityScenario.launch(ScoresActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assert(activity.findViewById<TextView>(R.id.tvScoreReflex) != null)
                assert(activity.findViewById<TextView>(R.id.tvScoreMatrix) != null)
                assert(activity.findViewById<Button>(R.id.btnBack) != null)
            }
        }
    }

    @Test
    fun testScoresDisplayZeroByDefault() {
        ActivityScenario.launch(ScoresActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val tvReflex = activity.findViewById<TextView>(R.id.tvScoreReflex)
                val tvMatrix = activity.findViewById<TextView>(R.id.tvScoreMatrix)
                assert(tvReflex.text.toString() == "0")
                assert(tvMatrix.text.toString() == "0")
            }
        }
    }

    @Test
    fun testBackButtonFinishesActivity() {
        ActivityScenario.launch(ScoresActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val btnBack = activity.findViewById<Button>(R.id.btnBack)
                btnBack.performClick()
                assert(scenario.isFinished)
            }
        }
    }

    @Test
    fun testScoresReflectSavedValues() {
        ActivityScenario.launch(ScoresActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                // Save some scores
                val prefs = activity.getSharedPreferences("cyberreflex", android.content.Context.MODE_PRIVATE)
                prefs.edit().putInt("best_reflex", 150).apply()
                prefs.edit().putInt("best_matrix", 200).apply()

                // Launch ScoresActivity again
                val intent = Intent(activity, ScoresActivity::class.java)
                ActivityScenario.launch<ScoresActivity>(intent).use { scenario2 ->
                    scenario2.onActivity { activity2 ->
                        val tvReflex = activity2.findViewById<TextView>(R.id.tvScoreReflex)
                        val tvMatrix = activity2.findViewById<TextView>(R.id.tvScoreMatrix)
                        assert(tvReflex.text.toString() == "150")
                        assert(tvMatrix.text.toString() == "200")
                    }
                }
            }
        }
    }
}
