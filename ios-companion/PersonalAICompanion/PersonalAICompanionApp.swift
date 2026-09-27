import SwiftUI
import UserNotifications
import UIKit

final class CompanionAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application:UIApplication,didFinishLaunchingWithOptions launchOptions:[UIApplication.LaunchOptionsKey:Any]?=nil)->Bool {
        BackgroundCoordinator.shared.register { NotificationCenter.default.post(name:.personalAIBackgroundRefresh,object:nil) }
        UNUserNotificationCenter.current().delegate=self
        UNUserNotificationCenter.current().requestAuthorization(options:[.alert,.sound,.badge]) { granted,_ in
            if granted { DispatchQueue.main.async { application.registerForRemoteNotifications() } }
        }
        return true
    }
    func application(_ application:UIApplication,didRegisterForRemoteNotificationsWithDeviceToken deviceToken:Data) {
        let token=deviceToken.map { String(format:"%02x",$0) }.joined()
        UserDefaults.standard.set(token,forKey:"personal_ai_apns_token")
        NotificationCenter.default.post(name:.personalAIAPNSToken,object:token)
    }
    func application(_ application:UIApplication,didFailToRegisterForRemoteNotificationsWithError error:Error) {
        NotificationCenter.default.post(name:.personalAIAPNSError,object:error.localizedDescription)
    }
    func userNotificationCenter(_ center:UNUserNotificationCenter,willPresent notification:UNNotification,withCompletionHandler completionHandler:@escaping (UNNotificationPresentationOptions)->Void) {
        completionHandler([.banner,.sound,.badge])
    }
}

extension Notification.Name {
    static let personalAIAPNSToken=Notification.Name("personalAIAPNSToken")
    static let personalAIAPNSError=Notification.Name("personalAIAPNSError")
    static let personalAIBackgroundRefresh=Notification.Name("personalAIBackgroundRefresh")
}

@main
struct PersonalAICompanionApp: App {
    @UIApplicationDelegateAdaptor(CompanionAppDelegate.self) private var appDelegate
    @StateObject private var store = CompanionStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                Form {
                    Section("Personal AI computer") {
                        TextField("https://your-computer:8766",text:$store.baseURL).textInputAutocapitalization(.never).keyboardType(.URL)
                        Toggle("Allow insecure local development",isOn:$store.allowInsecureDevelopment)
                        if store.allowInsecureDevelopment {
                            Text("Development only. HTTP/WS exposes pairing and bearer credentials to the local network.").font(.caption).foregroundStyle(.orange)
                        }
                    }
                    Section("Secure pairing") {
                        TextField("Pairing token from desktop",text:$store.pairingToken).textInputAutocapitalization(.never)
                        TextField("6-digit code",text:$store.pairingCode).keyboardType(.numberPad)
                        Button("Pair iPhone") { Task { await store.pair() } }
                    }
                    Section("Connection") {
                        LabeledContent("Status",value:store.status)
                        LabeledContent("Channel",value:store.connected ? "Connected" : "Offline")
                        HStack { Button("Connect") { store.connect() }; Button("Disconnect",role:.cancel) { store.disconnect() } }
                    }
                    Section("Voice") {
                        Toggle("Active voice session",isOn:Binding(get:{store.voiceActive},set:{ value in Task { await store.setVoiceActive(value) }}))
                        Text("Background audio is used only while an active voice session is running. Ordinary device connectivity follows iOS lifecycle rules.").font(.caption).foregroundStyle(.secondary)
                    }
                    Section("Notifications") {
                        Text("The iPhone registers its APNs token and sends it through the authenticated Personal AI device channel. A later APNs provider stage can use this registration for server-initiated background notifications.").font(.caption).foregroundStyle(.secondary)
                    }
                    Section("Security") {
                        Text("Device ID and bearer token are stored in the iPhone Keychain with this-device-only protection.").font(.caption)
                        Button("Forget this iPhone",role:.destructive) { store.forgetDevice() }
                    }
                }.navigationTitle("Personal AI")
            }
            .onAppear { if store.deviceID != nil { store.connect() } }
            .onChange(of:scenePhase) { _,phase in
                if phase == .active { store.connect() }
                if phase == .background { BackgroundCoordinator.shared.schedule() }
            }
        }
    }
}
