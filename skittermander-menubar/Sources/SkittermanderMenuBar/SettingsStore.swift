import Foundation
import WhisperKit

@MainActor
final class SettingsStore: ObservableObject {
    @Published var apiURL: String {
        didSet { UserDefaults.standard.set(apiURL, forKey: Self.apiURLKey) }
    }

    @Published var apiKey: String {
        didSet { UserDefaults.standard.set(apiKey, forKey: Self.apiKeyKey) }
    }

    @Published var userID: String {
        didSet { UserDefaults.standard.set(userID, forKey: Self.userIDKey) }
    }

    @Published var contextTokenTarget: Int {
        didSet { UserDefaults.standard.set(contextTokenTarget, forKey: Self.contextTargetKey) }
    }

    @Published var whisperModel: String {
        didSet { UserDefaults.standard.set(whisperModel, forKey: Self.whisperModelKey) }
    }

    private static let apiURLKey = "menubar.api_url"
    private static let apiKeyKey = "menubar.api_key"
    private static let userIDKey = "menubar.user_id"
    private static let contextTargetKey = "menubar.context_target"
    private static let whisperModelKey = "menubar.whisper_model"

    static let whisperModelOptions: [String] = ModelVariant.allCases.map(\.description)

    init() {
        let defaults = UserDefaults.standard
        self.apiURL = defaults.string(forKey: Self.apiURLKey) ?? "http://localhost:8000"
        self.apiKey = defaults.string(forKey: Self.apiKeyKey) ?? ""
        self.userID = defaults.string(forKey: Self.userIDKey) ?? "menubar.local"
        let savedTarget = defaults.integer(forKey: Self.contextTargetKey)
        self.contextTokenTarget = savedTarget > 0 ? savedTarget : 32_000
        let savedWhisperModel = defaults.string(forKey: Self.whisperModelKey) ?? "tiny"
        if Self.whisperModelOptions.contains(savedWhisperModel) {
            self.whisperModel = savedWhisperModel
        } else {
            self.whisperModel = "tiny"
        }
    }
}
