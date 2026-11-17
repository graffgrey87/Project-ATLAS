package com.atlas.cyberreflex

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class GameActivityTest {

    @Test
    fun activity_starts_with_correct_defaults() {
        val scenario = ActivityScenario.launch(GameActivity::class.java)
        scenario.onActivity { activity ->
            assertEquals("reflex", activity.mode)
            assertEquals("novice", activity.diff)
        }
        scenario.close()
    }

    @Test
    fun game_is_active_on_start() {
        val scenario = ActivityScenario.launch(GameActivity::class.java)
        scenario.onActivity { activity ->
            assertTrue(activity.gameActive)
        }
        scenario.close()
    }

    @Test
    fun combo_starts_at_zero() {
        val scenario = ActivityScenario.launch(GameActivity::class.java)
        scenario.onActivity { activity ->
            assertEquals(0, activity.combo)
        }
        scenario.close()
    }

    @Test
    fun score_starts_at_zero() {
        val scenario = ActivityScenario.launch(GameActivity::class.java)
        scenario.onActivity { activity ->
            assertEquals(0, activity.score)
        }
        scenario.close()
    }
}
