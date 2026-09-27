import Foundation
import Security
import UIKit
import UserNotifications
import BackgroundTasks
import AVFoundation
import Combine

struct PairRequest: Codable { let token:String; let code:String; let name:String; let platform:String }
struct PairResponse: Codable { struct Device:Codable { let id:String }; let device:Device; let bearer_token:String }

enum CompanionError: LocalizedError {
    case invalidBase, insecureTransport, notPaired, badResponse(String)
    var errorDescription:String? {
        switch self {
        case .invalidBase:return "Enter a valid Personal AI server URL."
        case .insecureTransport:return "Secure pairing requires HTTPS. Enable insecure development mode only on a trusted test network."
        case .notPaired:return "Pair this iPhone first."
        case .badResponse(let text):return text
        }
    }
}

final class KeychainStore {
    static let shared=KeychainStore(); private let service="ai.personal.companion.ios"
    func set(_ value:String,for key:String)throws {
        let data=Data(value.utf8); let query:[String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:key]
        SecItemDelete(query as CFDictionary); var add=query; add[kSecValueData as String]=data; add[kSecAttrAccessible as String]=kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status=SecItemAdd(add as CFDictionary,nil); guard status==errSecSuccess else { throw CompanionError.badResponse("Keychain error \(status)") }
    }
    func get(_ key:String)->String? {
        let query:[String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrAccount as String:key,kSecReturnData as String:true,kSecMatchLimit as String:kSecMatchLimitOne]
        var out:CFTypeRef?; guard SecItemCopyMatching(query as CFDictionary,&out)==errSecSuccess,let data=out as? Data else{return nil}; return String(data:data,encoding:.utf8)
    }
    func clear(){let query:[String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service];SecItemDelete(query as CFDictionary)}
}

@MainActor
final class CompanionStore: ObservableObject {
    @Published var baseURL=KeychainStore.shared.get("base") ?? ""
    @Published var pairingToken=""; @Published var pairingCode=""; @Published var status="Not paired"; @Published var connected=false; @Published var allowInsecureDevelopment=false; @Published var voiceActive=false
    let socket=DeviceSocket(); let voice=VoiceSession(); private let keychain=KeychainStore.shared; private var observers:[NSObjectProtocol]=[]
    var deviceID:String?{keychain.get("device")}; var bearer:String?{keychain.get("bearer")}

    init(){
        socket.onStatus={ [weak self] text,connected in Task{@MainActor in self?.status=text;self?.connected=connected} }
        socket.commandHandler={ [weak self] message in guard let self else{return ["ok":false,"error":"companion unavailable"]};return await self.handleCommand(message)}
        observers.append(NotificationCenter.default.addObserver(forName:.personalAIAPNSToken,object:nil,queue:.main){[weak self] note in guard let token=note.object as? String else{return};Task{await self?.socket.sendPushRegistration(token)}})
        observers.append(NotificationCenter.default.addObserver(forName:.personalAIAPNSError,object:nil,queue:.main){[weak self] note in
            guard let text=note.object as? String else{return}
            Task{@MainActor in self?.status="APNs registration unavailable: \(text)"}
        })
        observers.append(NotificationCenter.default.addObserver(forName:.personalAIBackgroundRefresh,object:nil,queue:.main){[weak self]_ in
            Task{@MainActor in self?.connect()}
        })
        if deviceID != nil { status="Paired" }
    }

    func pair()async {
        do{
            guard let base=URL(string:baseURL),let scheme=base.scheme?.lowercased(),["https","http"].contains(scheme) else{throw CompanionError.invalidBase}
            if scheme != "https" && !allowInsecureDevelopment{throw CompanionError.insecureTransport}
            var request=URLRequest(url:base.appending(path:"pair/confirm"));request.httpMethod="POST";request.setValue("application/json",forHTTPHeaderField:"Content-Type")
            request.httpBody=try JSONEncoder().encode(PairRequest(token:pairingToken,code:pairingCode,name:UIDevice.current.name,platform:"ios"))
            let(data,response)=try await URLSession.shared.data(for:request);guard let http=response as? HTTPURLResponse,(200..<300).contains(http.statusCode) else{throw CompanionError.badResponse(String(data:data,encoding:.utf8) ?? "Pairing failed")}
            let paired=try JSONDecoder().decode(PairResponse.self,from:data);try keychain.set(baseURL.trimmingCharacters(in:CharacterSet(charactersIn:"/")),for:"base");try keychain.set(paired.device.id,for:"device");try keychain.set(paired.bearer_token,for:"bearer")
            status="Paired as \(paired.device.id)";pairingToken="";pairingCode="";connect()
        }catch{status="Pair failed: \(error.localizedDescription)"}
    }

    func connect(){guard let base=keychain.get("base"),let device=deviceID,let bearer else{status="Pair first";return};socket.connect(base:base,deviceID:device,bearer:bearer,allowInsecure:allowInsecureDevelopment)}
    func disconnect(){socket.disconnect(reason:"User disconnected")}
    func forgetDevice(){socket.disconnect(reason:"Forgot device");keychain.clear();connected=false;status="Not paired"}
    func setVoiceActive(_ active:Bool)async{if active{do{try await voice.activate();voiceActive=true;status="Voice session ready"}catch{voiceActive=false;status="Voice unavailable: \(error.localizedDescription)"}}else{voice.deactivate();voiceActive=false}}

    private func handleCommand(_ message:[String:Any])async->[String:Any]{
        let action=message["action"] as? String ?? "";let params=message["parameters"] as? [String:Any] ?? [:]
        switch action{
        case "device_info":UIDevice.current.isBatteryMonitoringEnabled=true;return["ok":true,"result":["name":UIDevice.current.name,"system":"iOS","version":UIDevice.current.systemVersion,"model":UIDevice.current.model]]
        case "battery":UIDevice.current.isBatteryMonitoringEnabled=true;let level=UIDevice.current.batteryLevel;return["ok":true,"result":["percent":level<0 ? -1:Int(level*100),"state":UIDevice.current.batteryState.rawValue]]
        case "notification":let content=UNMutableNotificationContent();content.title=params["title"] as? String ?? "Personal AI";content.body=params["body"] as? String ?? "";do{try await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier:UUID().uuidString,content:content,trigger:nil));return["ok":true,"result":["delivered":true]]}catch{return["ok":false,"error":error.localizedDescription]}
        case "open_url","launch_app":guard let text=params["url"] as? String,let url=URL(string:text) else{return["ok":false,"error":"iOS requires a valid universal link or registered URL scheme in parameters.url"]};let opened=await UIApplication.shared.open(url);return["ok":opened,"result":["opened":opened]]
        case "voice_status":return["ok":true,"result":["active":voiceActive,"microphone_permission":voice.permissionDescription]]
        default:return["ok":false,"error":"Unsupported iOS action: \(action)"]
        }
    }
}

final class DeviceSocket:NSObject {
    var onStatus:((String,Bool)->Void)?;var commandHandler:(([String:Any])async->[String:Any])?
    private var task:URLSessionWebSocketTask?;private var reconnectWork:DispatchWorkItem?;private var config:(String,String,String,Bool)?;private var intentionallyClosed=false
    func connect(base:String,deviceID:String,bearer:String,allowInsecure:Bool){
        disconnect(reason:"Reconnect");intentionallyClosed=false;config=(base,deviceID,bearer,allowInsecure);guard var components=URLComponents(string:base)else{onStatus?("Invalid server URL",false);return}
        if components.scheme=="https"{components.scheme="wss"}else if components.scheme=="http" && allowInsecure{components.scheme="ws"}else{onStatus?("Secure WSS required",false);return}
        components.path=components.path.trimmingCharacters(in:CharacterSet(charactersIn:"/"))+"/device/ws/\(deviceID)";guard let url=components.url else{onStatus?("Invalid WebSocket URL",false);return}
        var request=URLRequest(url:url);request.setValue("Bearer \(bearer)",forHTTPHeaderField:"Authorization");let task=URLSession.shared.webSocketTask(with:request);self.task=task;task.resume();onStatus?("Connecting…",false)
        Task{await send(["type":"hello","device_id":deviceID,"platform":"ios","capabilities":["device_info","battery","notification","open_url","launch_app","voice_status"]]);if let token=UserDefaults.standard.string(forKey:"personal_ai_apns_token"){await sendPushRegistration(token)};await receiveLoop()}
    }
    func disconnect(reason:String){intentionallyClosed=true;reconnectWork?.cancel();task?.cancel(with:.normalClosure,reason:reason.data(using:.utf8));task=nil;onStatus?(reason,false)}
    private func scheduleReconnect(){guard !intentionallyClosed,let c=config else{return};let work=DispatchWorkItem{[weak self]in self?.connect(base:c.0,deviceID:c.1,bearer:c.2,allowInsecure:c.3)};reconnectWork=work;DispatchQueue.main.asyncAfter(deadline:.now()+3,execute:work)}
    private func receiveLoop()async{while !intentionallyClosed,let task{do{let message=try await task.receive();let text:String;switch message{case .string(let s):text=s;case .data(let d):text=String(data:d,encoding:.utf8) ?? "" @unknown default:text=""};guard let data=text.data(using:.utf8),let obj=try JSONSerialization.jsonObject(with:data) as? [String:Any] else{continue};if obj["type"] as? String=="command",let handler=commandHandler{var result=await handler(obj);result["type"]="result";result["request_id"]=obj["request_id"];await send(result)}else if obj["type"] as? String=="ack"{onStatus?("Connected",true)}}catch{onStatus?("Disconnected: \(error.localizedDescription)",false);scheduleReconnect();return}}}
    func sendPushRegistration(_ token:String)async{await send(["type":"push_registration","provider":"apns","token":token,"environment":"development"])}
    func send(_ dict:[String:Any])async{guard let task,JSONSerialization.isValidJSONObject(dict),let data=try? JSONSerialization.data(withJSONObject:dict),let text=String(data:data,encoding:.utf8)else{return};do{try await task.send(.string(text))}catch{onStatus?("Send failed: \(error.localizedDescription)",false)}}
}

final class VoiceSession {
    private let session=AVAudioSession.sharedInstance()
    var permissionDescription:String{
        switch AVAudioApplication.shared.recordPermission{
        case .granted:return "granted"
        case .denied:return "denied"
        default:return "undetermined"
        }
    }
    func activate()async throws{
        if AVAudioApplication.shared.recordPermission == AVAudioApplication.recordPermission.undetermined {
            let granted = await AVAudioApplication.requestRecordPermission()
            if !granted { throw CompanionError.badResponse("Microphone permission denied") }
        }
        guard AVAudioApplication.shared.recordPermission == AVAudioApplication.recordPermission.granted else {
            throw CompanionError.badResponse("Microphone permission denied")
        }
        try session.setCategory(.playAndRecord,mode:.voiceChat,options:[.allowBluetoothHFP,.defaultToSpeaker])
        try session.setActive(true)
    }
    func deactivate(){try? session.setActive(false,options:.notifyOthersOnDeactivation)}
}

final class BackgroundCoordinator {
    static let shared=BackgroundCoordinator();private let id="ai.personal.companion.refresh"
    func register(_ reconnect:@escaping()->Void){BGTaskScheduler.shared.register(forTaskWithIdentifier:id,using:nil){task in reconnect();self.schedule();task.setTaskCompleted(success:true)}}
    func schedule(){let request=BGAppRefreshTaskRequest(identifier:id);request.earliestBeginDate=Date(timeIntervalSinceNow:15*60);try? BGTaskScheduler.shared.submit(request)}
}
