package com.atlas.cyberreflex

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import android.widget.TextView

@RunWith(AndroidJUnit4::class)
class ScoresActivityTest {

    @Test
    fun activity_starts_successfully() {
        val scenario = ActivityScenario.launch(ScoresActivity::class.java)
        scenario.onActivity { activity ->
            assertNotNull(activity)
        }
        scenario.close()
    }

    @Test
    fun scores_display_zero_when_no_data() {
        val scenario = ActivityScenario.launch(ScoresActivity::class.java)
        scenario.onActivity { activity ->
            val tvReflex = activity.findViewById<TextView>(R.id.tvScoreReflex)
            val tvMatrix = activity.findViewById<TextView>(R.id.tvScoreMatrix)
            assertEquals("0", tvReflex.text.toString())
            assertEquals("0", tvMatrix.text.toString())
        }
        scenario.close()
    }
}
