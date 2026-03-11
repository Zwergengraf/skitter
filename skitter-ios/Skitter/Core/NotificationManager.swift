import Foundation
import UIKit
import UserNotifications

@MainActor
final class NotificationManager: ObservableObject {
    static let shared = NotificationManager()

    @Published private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published private(set) var deviceTokenHex: String
    @Published private(set) var registrationStatusText: String = ""

    private let defaults = UserDefaults.standard
    private let deviceTokenKey = "ios.apns_device_token"

    private init() {
        self.deviceTokenHex = defaults.string(forKey: deviceTokenKey) ?? ""
    }

    var authorizationLabel: String {
        switch authorizationStatus {
        case .authorized:
            return "Authorized"
        case .denied:
            return "Denied"
        case .ephemeral:
            return "Ephemeral"
        case .provisional:
            return "Provisional"
        case .notDetermined:
            return "Not requested"
        @unknown default:
            return "Unknown"
        }
    }

    var canDeliverAlerts: Bool {
        authorizationStatus == .authorized || authorizationStatus == .provisional || authorizationStatus == .ephemeral
    }

    func refreshAuthorizationStatus() async {
        let status = await notificationStatus()
        authorizationStatus = status
    }

    func requestAuthorizationAndRegister() async {
        do {
            let granted = try await requestAuthorization()
            await refreshAuthorizationStatus()
            if granted {
                registrationStatusText = "Registering this device for notifications..."
                UIApplication.shared.registerForRemoteNotifications()
            } else {
                registrationStatusText = "Notifications were not enabled."
            }
        } catch {
            registrationStatusText = error.localizedDescription
        }
    }

    func handleRegisteredDeviceToken(_ tokenData: Data) {
        let hex = tokenData.map { String(format: "%02x", $0) }.joined()
        deviceTokenHex = hex
        defaults.set(hex, forKey: deviceTokenKey)
        registrationStatusText = "APNs token captured locally."
    }

    func handleRemoteRegistrationFailure(_ error: Error) {
        registrationStatusText = "APNs registration failed: \(error.localizedDescription)"
    }

    func updateBadgeCount(_ count: Int) {
        UNUserNotificationCenter.current().setBadgeCount(max(0, count)) { [weak self] error in
            guard let self, let error else { return }
            Task { @MainActor in
                self.registrationStatusText = "Badge update failed: \(error.localizedDescription)"
            }
        }
    }

    func scheduleAssistantReplyNotification(message: ChatMessage) {
        guard canDeliverAlerts else { return }

        let content = UNMutableNotificationContent()
        content.title = "Skitter replied"
        let trimmed = message.content.trimmingCharacters(in: .whitespacesAndNewlines)
        content.body = trimmed.isEmpty ? "Open the app to view the latest response." : String(trimmed.prefix(180))
        content.sound = .default
        content.userInfo = ["message_id": message.id]

        let request = UNNotificationRequest(
            identifier: "assistant-reply-\(message.id)",
            content: content,
            trigger: nil
        )

        UNUserNotificationCenter.current().add(request) { [weak self] error in
            guard let self else { return }
            if let error {
                Task { @MainActor in
                    self.registrationStatusText = "Notification delivery failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func requestAuthorization() async throws -> Bool {
        try await withCheckedThrowingContinuation { continuation in
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: granted)
                }
            }
        }
    }

    private func notificationStatus() async -> UNAuthorizationStatus {
        await withCheckedContinuation { continuation in
            UNUserNotificationCenter.current().getNotificationSettings { settings in
                continuation.resume(returning: settings.authorizationStatus)
            }
        }
    }
}
