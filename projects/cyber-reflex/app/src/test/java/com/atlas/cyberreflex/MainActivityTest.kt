package com.atlas.cyberreflex

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import android.widget.RadioGroup

@RunWith(AndroidJUnit4::class)
class MainActivityTest {

    @Test
    fun activity_starts_successfully() {
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            assertNotNull(activity)
        }
        scenario.close()
    }

    @Test
    fun default_mode_is_reflex() {
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            val rgMode = activity.findViewById<RadioGroup>(R.id.rgMode)
            assertEquals(R.id.rbReflex, rgMode.checkedRadioButtonId)
        }
        scenario.close()
    }

    @Test
    fun default_diff_is_novice() {
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            val rgDiff = activity.findViewById<RadioGroup>(R.id.rgDiff)
            assertEquals(R.id.rbNovice, rgDiff.checkedRadioButtonId)
        }
        scenario.close()
    }
}
