package ai.personal.companion
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import androidx.test.core.app.ActivityScenario
import android.widget.ScrollView
import android.widget.LinearLayout
import android.widget.Button
import android.view.View
import org.junit.Test
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class SmokeInstrumentedTest{
 @Test fun appContextAndServiceExist(){val c=InstrumentationRegistry.getInstrumentation().targetContext;assertEquals("ai.personal.companion",c.packageName);assertNotNull(Class.forName("ai.personal.companion.DeviceCommandService"))}
 @Test fun pairingSurfaceScrollsAndHasComfortableControls(){
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   scenario.onActivity { activity ->
    val content = activity.findViewById<android.view.ViewGroup>(android.R.id.content)
    val scroll = content.getChildAt(0) as ScrollView
    val rows = scroll.getChildAt(0) as LinearLayout
    val open = rows.getChildAt(2) as Button
    val advanced = rows.getChildAt(4) as Button
    val pairing = rows.getChildAt(5) as LinearLayout
    assertTrue(open.minHeight >= (48 * activity.resources.displayMetrics.density).toInt())
    assertEquals(View.GONE, pairing.visibility)
    advanced.performClick()
    assertEquals(View.VISIBLE, pairing.visibility)
    advanced.performClick()
    assertEquals(View.GONE, pairing.visibility)
   }
  }
 }
}
