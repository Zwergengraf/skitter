import Foundation
import Security

@MainActor
final class SettingsStore: ObservableObject {
    @Published var apiURL: String {
        didSet {
            defaults.set(apiURL, forKey: Keys.apiURL)
        }
    }

    @Published var apiKey: String {
        didSet {
            persistToken(apiKey)
        }
    }

    @Published var conversationSilenceSeconds: Double {
        didSet {
            defaults.set(conversationSilenceSeconds, forKey: Keys.conversationSilenceSeconds)
        }
    }

    @Published var preferredVoiceModel: String {
        didSet {
            defaults.set(preferredVoiceModel, forKey: Keys.preferredVoiceModel)
        }
    }

    @Published var speechRecognitionLocaleIdentifier: String {
        didSet {
            defaults.set(speechRecognitionLocaleIdentifier, forKey: Keys.speechRecognitionLocaleIdentifier)
        }
    }

    @Published var speechSynthesisVoiceIdentifier: String {
        didSet {
            defaults.set(speechSynthesisVoiceIdentifier, forKey: Keys.speechSynthesisVoiceIdentifier)
        }
    }

    @Published var speaksReplies: Bool {
        didSet {
            defaults.set(speaksReplies, forKey: Keys.speaksReplies)
        }
    }

    @Published var hasPromptedForNotifications: Bool {
        didSet {
            defaults.set(hasPromptedForNotifications, forKey: Keys.hasPromptedForNotifications)
        }
    }

    private let defaults: UserDefaults

    private enum Keys {
        static let apiURL = "ios.api_url"
        static let conversationSilenceSeconds = "ios.conversation_silence_seconds"
        static let preferredVoiceModel = "ios.preferred_voice_model"
        static let speechRecognitionLocaleIdentifier = "ios.speech_recognition_locale_identifier"
        static let speechSynthesisVoiceIdentifier = "ios.speech_synthesis_voice_identifier"
        static let speaksReplies = "ios.speaks_replies"
        static let hasPromptedForNotifications = "ios.has_prompted_for_notifications"
    }

    private enum KeychainKeys {
        static let service = "io.skitter.ios"
        static let account = "api-token"
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.apiURL = defaults.string(forKey: Keys.apiURL) ?? "http://127.0.0.1:8000"
        self.apiKey = Self.readToken(service: KeychainKeys.service, account: KeychainKeys.account) ?? ""
        let savedSilence = defaults.double(forKey: Keys.conversationSilenceSeconds)
        self.conversationSilenceSeconds = savedSilence > 0 ? savedSilence : 1.2
        self.preferredVoiceModel = defaults.string(forKey: Keys.preferredVoiceModel) ?? ""
        self.speechRecognitionLocaleIdentifier = defaults.string(forKey: Keys.speechRecognitionLocaleIdentifier) ?? ""
        self.speechSynthesisVoiceIdentifier = defaults.string(forKey: Keys.speechSynthesisVoiceIdentifier) ?? ""
        self.speaksReplies = defaults.object(forKey: Keys.speaksReplies) as? Bool ?? true
        self.hasPromptedForNotifications = defaults.bool(forKey: Keys.hasPromptedForNotifications)
    }

    var hasToken: Bool {
        !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var effectiveSpeechRecognitionLocaleIdentifier: String {
        let cleaned = speechRecognitionLocaleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? Locale.current.identifier : cleaned
    }

    var defaultSpeechSynthesisLanguageIdentifier: String {
        SpeechVoiceCatalog.defaultLanguageIdentifier()
    }

    var effectiveSpeechSynthesisVoiceIdentifier: String? {
        let cleaned = speechSynthesisVoiceIdentifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if !cleaned.isEmpty {
            return cleaned
        }
        return SpeechVoiceCatalog.bestAvailableVoiceIdentifier(for: defaultSpeechSynthesisLanguageIdentifier)
    }

    func eraseAuth() {
        apiKey = ""
    }

    private func persistToken(_ token: String) {
        let cleaned = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            Self.deleteToken(service: KeychainKeys.service, account: KeychainKeys.account)
        } else {
            Self.writeToken(cleaned, service: KeychainKeys.service, account: KeychainKeys.account)
        }
    }

    private static func readToken(service: String, account: String) -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private static func writeToken(_ token: String, service: String, account: String) {
        let data = Data(token.utf8)
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        let attributes: [CFString: Any] = [
            kSecValueData: data,
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query
            insert[kSecValueData] = data
            SecItemAdd(insert as CFDictionary, nil)
        }
    }

    private static func deleteToken(service: String, account: String) {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
