package com.atlas.cyberreflex

import android.content.Intent
import android.widget.RadioGroup
import android.widget.Button
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso
import androidx.test.espresso.action.ViewActions
import androidx.test.espresso.assertion.ViewAssertions
import androidx.test.espresso.matcher.ViewMatchers
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class MainActivityTest {

    @Test
    fun testMainActivityLaunches() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assert(activity.findViewById<RadioGroup>(R.id.rgMode) != null)
                assert(activity.findViewById<RadioGroup>(R.id.rgDiff) != null)
                assert(activity.findViewById<Button>(R.id.btnStart) != null)
                assert(activity.findViewById<Button>(R.id.btnScores) != null)
            }
        }
    }

    @Test
    fun testStartButtonNavigatesToGameActivity() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val btnStart = activity.findViewById<Button>(R.id.btnStart)
                btnStart.performClick()
                // GameActivity should be launched
                assert(scenario.currentActivity != null)
            }
        }
    }

    @Test
    fun testScoresButtonNavigatesToScoresActivity() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val btnScores = activity.findViewById<Button>(R.id.btnScores)
                btnScores.performClick()
                assert(scenario.currentActivity != null)
            }
        }
    }

    @Test
    fun testDefaultModeIsReflex() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rgMode = activity.findViewById<RadioGroup>(R.id.rgMode)
                assert(rgMode.checkedRadioButtonId == R.id.rbReflex)
            }
        }
    }

    @Test
    fun testDefaultDifficultyIsNovice() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rgDiff = activity.findViewById<RadioGroup>(R.id.rgDiff)
                assert(rgDiff.checkedRadioButtonId == R.id.rbNovice)
            }
        }
    }

    @Test
    fun testSwitchModeToMatrix() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rgMode = activity.findViewById<RadioGroup>(R.id.rgMode)
                rgMode.check(R.id.rbMatrix)
                assert(rgMode.checkedRadioButtonId == R.id.rbMatrix)
            }
        }
    }

    @Test
    fun testSwitchDifficultyToPro() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rgDiff = activity.findViewById<RadioGroup>(R.id.rgDiff)
                rgDiff.check(R.id.rbPro)
                assert(rgDiff.checkedRadioButtonId == R.id.rbPro)
            }
        }
    }

    @Test
    fun testSwitchDifficultyToCyber() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rgDiff = activity.findViewById<RadioGroup>(R.id.rgDiff)
                rgDiff.check(R.id.rbCyber)
                assert(rgDiff.checkedRadioButtonId == R.id.rbCyber)
            }
        }
    }
}
