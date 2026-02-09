import Foundation

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

    private static let apiURLKey = "menubar.api_url"
    private static let apiKeyKey = "menubar.api_key"
    private static let userIDKey = "menubar.user_id"
    private static let contextTargetKey = "menubar.context_target"

    init() {
        let defaults = UserDefaults.standard
        self.apiURL = defaults.string(forKey: Self.apiURLKey) ?? "http://localhost:8000"
        self.apiKey = defaults.string(forKey: Self.apiKeyKey) ?? ""
        self.userID = defaults.string(forKey: Self.userIDKey) ?? "menubar.local"
        let savedTarget = defaults.integer(forKey: Self.contextTargetKey)
        self.contextTokenTarget = savedTarget > 0 ? savedTarget : 32_000
    }
}
