import Foundation
import Speech

struct SpeechRecognitionLocaleOption: Identifiable, Hashable {
    let id: String
    let title: String
}

@MainActor
final class SettingsStore: ObservableObject {
    @Published var apiURL: String {
        didSet { UserDefaults.standard.set(apiURL, forKey: Self.apiURLKey) }
    }

    @Published var apiKey: String {
        didSet { UserDefaults.standard.set(apiKey, forKey: Self.apiKeyKey) }
    }

    @Published var selectedProfileSlug: String {
        didSet { UserDefaults.standard.set(selectedProfileSlug, forKey: Self.selectedProfileSlugKey) }
    }

    @Published var contextTokenTarget: Int {
        didSet { UserDefaults.standard.set(contextTokenTarget, forKey: Self.contextTargetKey) }
    }

    @Published var speechRecognitionLocaleIdentifier: String {
        didSet { UserDefaults.standard.set(speechRecognitionLocaleIdentifier, forKey: Self.speechRecognitionLocaleIdentifierKey) }
    }

    @Published var speechRecognitionRequiresOnDevice: Bool {
        didSet { UserDefaults.standard.set(speechRecognitionRequiresOnDevice, forKey: Self.speechRecognitionRequiresOnDeviceKey) }
    }

    @Published var conversationSilenceSeconds: Double {
        didSet { UserDefaults.standard.set(conversationSilenceSeconds, forKey: Self.conversationSilenceSecondsKey) }
    }

    @Published var conversationModelName: String {
        didSet { UserDefaults.standard.set(conversationModelName, forKey: Self.conversationModelNameKey) }
    }

    @Published var openAIBaseURL: String {
        didSet { UserDefaults.standard.set(openAIBaseURL, forKey: Self.openAIBaseURLKey) }
    }

    @Published var openAIAPIKey: String {
        didSet { UserDefaults.standard.set(openAIAPIKey, forKey: Self.openAIAPIKeyKey) }
    }

    @Published var openAITTSModel: String {
        didSet { UserDefaults.standard.set(openAITTSModel, forKey: Self.openAITTSModelKey) }
    }

    @Published var openAITTSVoice: String {
        didSet { UserDefaults.standard.set(openAITTSVoice, forKey: Self.openAITTSVoiceKey) }
    }

    private static let apiURLKey = "menubar.api_url"
    private static let apiKeyKey = "menubar.api_key"
    private static let selectedProfileSlugKey = "menubar.selected_profile_slug"
    private static let contextTargetKey = "menubar.context_target"
    private static let speechRecognitionLocaleIdentifierKey = "menubar.speech_recognition_locale_identifier"
    private static let speechRecognitionRequiresOnDeviceKey = "menubar.speech_recognition_requires_on_device"
    private static let conversationSilenceSecondsKey = "menubar.conversation_silence_seconds"
    private static let conversationModelNameKey = "menubar.conversation_model_name"
    private static let openAIBaseURLKey = "menubar.openai_base_url"
    private static let openAIAPIKeyKey = "menubar.openai_api_key"
    private static let openAITTSModelKey = "menubar.openai_tts_model"
    private static let openAITTSVoiceKey = "menubar.openai_tts_voice"

    static var speechRecognitionLocaleOptions: [SpeechRecognitionLocaleOption] {
        let supported = SFSpeechRecognizer.supportedLocales()
        let commonIdentifiers = [
            "en-US",
            "en-GB",
            "ja-JP",
            "de-DE",
            "fr-FR",
            "es-ES",
            "it-IT",
            "pt-BR",
            "zh-CN",
            "ko-KR",
        ]
        let common = commonIdentifiers.compactMap { identifier in
            supported.contains { $0.identifier == identifier } ? localeOption(identifier: identifier) : nil
        }
        let commonIDs = Set(common.map(\.id))
        let rest = supported
            .map(\.identifier)
            .filter { !commonIDs.contains($0) }
            .sorted { localeDisplayName(for: $0) < localeDisplayName(for: $1) }
            .map(localeOption(identifier:))

        return [SpeechRecognitionLocaleOption(id: "", title: "System Default")] + common + rest
    }

    var effectiveSpeechRecognitionLocaleIdentifier: String {
        let cleaned = speechRecognitionLocaleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? Locale.current.identifier : cleaned
    }

    init() {
        let defaults = UserDefaults.standard
        self.apiURL = defaults.string(forKey: Self.apiURLKey) ?? "http://localhost:8000"
        self.apiKey = defaults.string(forKey: Self.apiKeyKey) ?? ""
        self.selectedProfileSlug = defaults.string(forKey: Self.selectedProfileSlugKey) ?? ""
        let savedTarget = defaults.integer(forKey: Self.contextTargetKey)
        self.contextTokenTarget = savedTarget > 0 ? savedTarget : 256_000
        self.speechRecognitionLocaleIdentifier = defaults.string(forKey: Self.speechRecognitionLocaleIdentifierKey) ?? ""
        self.speechRecognitionRequiresOnDevice = defaults.bool(forKey: Self.speechRecognitionRequiresOnDeviceKey)
        let savedSilenceSeconds = defaults.double(forKey: Self.conversationSilenceSecondsKey)
        self.conversationSilenceSeconds = savedSilenceSeconds > 0 ? savedSilenceSeconds : 1.2
        self.conversationModelName = defaults.string(forKey: Self.conversationModelNameKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        self.openAIBaseURL = defaults.string(forKey: Self.openAIBaseURLKey) ?? "https://api.openai.com/v1"
        self.openAIAPIKey = defaults.string(forKey: Self.openAIAPIKeyKey) ?? ""
        self.openAITTSModel = defaults.string(forKey: Self.openAITTSModelKey) ?? "gpt-4o-mini-tts"
        self.openAITTSVoice = defaults.string(forKey: Self.openAITTSVoiceKey) ?? "alloy"
    }

    private static func localeOption(identifier: String) -> SpeechRecognitionLocaleOption {
        SpeechRecognitionLocaleOption(id: identifier, title: localeDisplayName(for: identifier))
    }

    private static func localeDisplayName(for identifier: String) -> String {
        let current = Locale.current
        let name = current.localizedString(forIdentifier: identifier)
            ?? Locale(identifier: identifier).localizedString(forIdentifier: identifier)
            ?? identifier
        return "\(name) (\(identifier))"
    }
}
