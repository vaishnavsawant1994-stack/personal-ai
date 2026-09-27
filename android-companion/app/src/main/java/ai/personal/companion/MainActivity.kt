package ai.personal.companion

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

class MainActivity : AppCompatActivity() {
    private val client = OkHttpClient()
    private lateinit var status: TextView
    private lateinit var base: EditText
    private lateinit var pairToken: EditText
    private lateinit var code: EditText

    private val prefs by lazy {
        val key = MasterKey.Builder(this)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            this,
            "personal_ai_device",
            key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        base = EditText(this).apply {
            hint = "http://PC:8766"
            setText(prefs.getString("base", "") ?: "")
        }
        pairToken = EditText(this).apply { hint = "Pairing token from desktop" }
        code = EditText(this).apply { hint = "6-digit code" }
        status = TextView(this).apply { text = "Not paired" }
        val pair = Button(this).apply { text = "Pair" }
        val connect = Button(this).apply { text = "Start background connection" }
        listOf(base, pairToken, code, pair, connect, status).forEach(box::addView)
        setContentView(box)
        pair.setOnClickListener { pairDevice() }
        connect.setOnClickListener { startDeviceService() }
        if (prefs.getString("device", null) != null) startDeviceService()
    }

    private fun pairDevice() {
        val payload = JSONObject()
        payload.put("token", pairToken.text.toString())
        payload.put("code", code.text.toString())
        payload.put("name", android.os.Build.MODEL)
        payload.put("platform", "android")
        val body = payload.toString().toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url(base.text.toString().trimEnd('/') + "/pair/confirm")
            .post(body)
            .build()
        client.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread { status.text = "Pair failed: ${e.message}" }
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    val text = it.body?.string().orEmpty()
                    if (!it.isSuccessful) {
                        runOnUiThread { status.text = "Pair failed: $text" }
                        return
                    }
                    val obj = JSONObject(text)
                    val device = obj.getJSONObject("device").getString("id")
                    val bearer = obj.getString("bearer_token")
                    prefs.edit()
                        .putString("base", base.text.toString())
                        .putString("device", device)
                        .putString("bearer", bearer)
                        .apply()
                    runOnUiThread {
                        status.text = "Paired as $device"
                        startDeviceService()
                    }
                }
            }
        })
    }

    private fun startDeviceService() {
        if (prefs.getString("device", null) == null) {
            status.text = "Pair first"
            return
        }
        ContextCompat.startForegroundService(this, Intent(this, DeviceCommandService::class.java))
        status.text = "Background connection active"
    }
}
