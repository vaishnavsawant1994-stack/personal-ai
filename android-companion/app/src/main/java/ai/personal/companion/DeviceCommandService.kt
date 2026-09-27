package ai.personal.companion

import android.app.*
import android.content.*
import android.hardware.camera2.CameraManager
import android.net.Uri
import android.os.*
import androidx.core.app.NotificationCompat
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.*
import org.json.JSONObject

class DeviceCommandService: Service() {
  private val client=OkHttpClient.Builder().retryOnConnectionFailure(true).build(); private var ws:WebSocket?=null
  private val prefs by lazy { val key=MasterKey.Builder(this).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(); EncryptedSharedPreferences.create(this,"personal_ai_device",key,EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM) }
  override fun onCreate(){super.onCreate(); val channel=NotificationChannel("personal_ai_device","Personal AI Device",NotificationManager.IMPORTANCE_LOW); getSystemService(NotificationManager::class.java).createNotificationChannel(channel); startForeground(7,NotificationCompat.Builder(this,"personal_ai_device").setContentTitle("Personal AI connected").setContentText("Secure device command channel active").setSmallIcon(android.R.drawable.stat_notify_sync).build()); connect()}
  override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{if(ws==null)connect();return START_STICKY}
  override fun onBind(intent:Intent?)=null
  private fun connect(){val base=prefs.getString("base",null)?:return; val device=prefs.getString("device",null)?:return; val bearer=prefs.getString("bearer",null)?:return; val url=base.replaceFirst("http://","ws://").replaceFirst("https://","wss://").trimEnd('/')+"/device/ws/$device"; val req=Request.Builder().url(url).addHeader("Authorization","Bearer $bearer").build(); ws=client.newWebSocket(req,object:WebSocketListener(){override fun onOpen(w:WebSocket,r:Response){w.send(JSONObject().put("type","hello").put("device_id",device).toString())}; override fun onMessage(w:WebSocket,text:String){handle(w,JSONObject(text))}; override fun onFailure(w:WebSocket,t:Throwable,r:Response?){ws=null; Handler(Looper.getMainLooper()).postDelayed({connect()},3000)}})}
  private fun handle(w:WebSocket,msg:JSONObject){if(msg.optString("type")!="command")return; val id=msg.optString("request_id"); val action=msg.optString("action"); val p=msg.optJSONObject("parameters")?:JSONObject(); try{val result=when(action){"device_info"->JSONObject().put("manufacturer",Build.MANUFACTURER).put("model",Build.MODEL).put("sdk",Build.VERSION.SDK_INT);"battery"->{val bm=getSystemService(BATTERY_SERVICE) as BatteryManager; JSONObject().put("percent",bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))};"flashlight"->{val cm=getSystemService(CameraManager::class.java); val id0=cm.cameraIdList.first(); cm.setTorchMode(id0,p.optBoolean("enabled",true)); JSONObject().put("enabled",p.optBoolean("enabled",true))};"open_url"->{val i=Intent(Intent.ACTION_VIEW,Uri.parse(p.getString("url"))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);startActivity(i);JSONObject().put("opened",true)};"launch_app"->{val i=packageManager.getLaunchIntentForPackage(p.getString("package"))?:throw IllegalArgumentException("package not launchable");i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);startActivity(i);JSONObject().put("launched",true)};else->throw IllegalArgumentException("unsupported action")};w.send(JSONObject().put("type","result").put("request_id",id).put("ok",true).put("result",result).toString())}catch(e:Exception){w.send(JSONObject().put("type","result").put("request_id",id).put("ok",false).put("error",e.message).toString())}}
  override fun onDestroy(){ws?.close(1000,"service stopping");super.onDestroy()}
}
