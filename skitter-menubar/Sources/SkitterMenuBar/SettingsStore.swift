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

    @Published var contextTokenTarget: Int {
        didSet { UserDefaults.standard.set(contextTokenTarget, forKey: Self.contextTargetKey) }
    }

    @Published var whisperModel: String {
        didSet { UserDefaults.standard.set(whisperModel, forKey: Self.whisperModelKey) }
    }

    @Published private(set) var whisperModelFolders: [String: String] {
        didSet { persistWhisperModelFolders() }
    }

    private static let apiURLKey = "menubar.api_url"
    private static let apiKeyKey = "menubar.api_key"
    private static let contextTargetKey = "menubar.context_target"
    private static let whisperModelKey = "menubar.whisper_model"
    private static let whisperModelFoldersKey = "menubar.whisper_model_folders"

    static let whisperModelOptions: [String] = ModelVariant.allCases.map(\.description)

    init() {
        let defaults = UserDefaults.standard
        self.apiURL = defaults.string(forKey: Self.apiURLKey) ?? "http://localhost:8000"
        self.apiKey = defaults.string(forKey: Self.apiKeyKey) ?? ""
        let savedTarget = defaults.integer(forKey: Self.contextTargetKey)
        self.contextTokenTarget = savedTarget > 0 ? savedTarget : 256_000
        let savedWhisperModel = defaults.string(forKey: Self.whisperModelKey) ?? "medium"
        if Self.whisperModelOptions.contains(savedWhisperModel) {
            self.whisperModel = savedWhisperModel
        } else {
            self.whisperModel = "medium"
        }
        self.whisperModelFolders = Self.loadWhisperModelFolders(defaults: defaults)
    }

    func whisperModelFolder(for model: String) -> String? {
        let key = model.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return nil }
        let raw = whisperModelFolders[key]?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let raw, !raw.isEmpty {
            return raw
        }
        return nil
    }

    func setWhisperModelFolder(_ path: String, for model: String) {
        let modelKey = model.trimmingCharacters(in: .whitespacesAndNewlines)
        let value = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !modelKey.isEmpty else { return }
        var map = whisperModelFolders
        if value.isEmpty {
            map.removeValue(forKey: modelKey)
        } else {
            map[modelKey] = value
        }
        whisperModelFolders = map
    }

    private static func loadWhisperModelFolders(defaults: UserDefaults) -> [String: String] {
        guard let raw = defaults.string(forKey: Self.whisperModelFoldersKey), !raw.isEmpty else {
            return [:]
        }
        guard let data = raw.data(using: .utf8) else {
            return [:]
        }
        guard let decoded = try? JSONDecoder().decode([String: String].self, from: data) else {
            return [:]
        }
        return decoded
    }

    private func persistWhisperModelFolders() {
        guard let data = try? JSONEncoder().encode(whisperModelFolders),
              let raw = String(data: data, encoding: .utf8)
        else {
            return
        }
        UserDefaults.standard.set(raw, forKey: Self.whisperModelFoldersKey)
    }
}
