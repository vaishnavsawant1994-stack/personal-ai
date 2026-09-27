package ai.personal.companion
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class SmokeInstrumentedTest{
 @Test fun appContextAndServiceExist(){val c=InstrumentationRegistry.getInstrumentation().targetContext;assertEquals("ai.personal.companion",c.packageName);assertNotNull(Class.forName("ai.personal.companion.DeviceCommandService"))}
}
