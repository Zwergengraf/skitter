import AVFoundation
import Foundation

struct SpeechVoiceOption: Identifiable, Hashable {
    let id: String
    let title: String
}

@MainActor
enum SpeechVoiceCatalog {
    private struct CachedLanguageData {
        let rankedVoices: [AVSpeechSynthesisVoice]
        let options: [SpeechVoiceOption]
        let automaticTitle: String
        let bestVoiceIdentifier: String?
    }

    private static let allVoices: [AVSpeechSynthesisVoice] = AVSpeechSynthesisVoice.speechVoices()
        .filter(shouldInclude)

    private static var voicesByIdentifier: [String: AVSpeechSynthesisVoice] = {
        Dictionary(uniqueKeysWithValues: allVoices.map { ($0.identifier, $0) })
    }()

    private static var labelsByIdentifier: [String: String] = {
        Dictionary(uniqueKeysWithValues: allVoices.map { ($0.identifier, label(for: $0)) })
    }()

    private static var cachedLanguageData: [String: CachedLanguageData] = [:]

    static func defaultLanguageIdentifier() -> String {
        let preferred = Locale.preferredLanguages.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return preferred.isEmpty ? Locale.current.identifier : preferred
    }

    static func availableOptions(for preferredLanguageIdentifier: String) -> [SpeechVoiceOption] {
        languageData(for: preferredLanguageIdentifier).options
    }

    static func automaticTitle(for preferredLanguageIdentifier: String) -> String {
        languageData(for: preferredLanguageIdentifier).automaticTitle
    }

    static func title(for identifier: String, preferredLanguageIdentifier: String) -> String {
        let cleaned = cleanedIdentifier(identifier)
        guard !cleaned.isEmpty else {
            return automaticTitle(for: preferredLanguageIdentifier)
        }
        if let cachedLabel = labelsByIdentifier[cleaned] {
            return cachedLabel
        }
        guard let voice = AVSpeechSynthesisVoice(identifier: cleaned) else {
            return "Unavailable voice"
        }
        voicesByIdentifier[cleaned] = voice
        let resolvedLabel = label(for: voice)
        labelsByIdentifier[cleaned] = resolvedLabel
        return resolvedLabel
    }

    static func bestAvailableVoiceIdentifier(for preferredLanguageIdentifier: String) -> String? {
        languageData(for: preferredLanguageIdentifier).bestVoiceIdentifier
    }

    static func resolveVoice(
        preferredIdentifier: String?,
        preferredLanguageIdentifier: String
    ) -> AVSpeechSynthesisVoice? {
        let cleaned = cleanedIdentifier(preferredIdentifier)
        if !cleaned.isEmpty {
            if let explicitVoice = voicesByIdentifier[cleaned] {
                return explicitVoice
            }
            if let explicitVoice = AVSpeechSynthesisVoice(identifier: cleaned) {
                voicesByIdentifier[cleaned] = explicitVoice
                labelsByIdentifier[cleaned] = label(for: explicitVoice)
                return explicitVoice
            }
        }
        return resolveAutomaticVoice(preferredLanguageIdentifier: preferredLanguageIdentifier)
            ?? AVSpeechSynthesisVoice(language: preferredLanguageIdentifier)
    }

    private static func resolveAutomaticVoice(preferredLanguageIdentifier: String) -> AVSpeechSynthesisVoice? {
        languageData(for: preferredLanguageIdentifier).rankedVoices.first
    }

    private static func languageData(for preferredLanguageIdentifier: String) -> CachedLanguageData {
        let key = cleanedIdentifier(preferredLanguageIdentifier).isEmpty
            ? defaultLanguageIdentifier()
            : cleanedIdentifier(preferredLanguageIdentifier)
        if let cached = cachedLanguageData[key] {
            return cached
        }

        let rankedVoices = allVoices.sorted { lhs, rhs in
            if languageMatchRank(for: lhs, preferredLanguageIdentifier: key)
                != languageMatchRank(for: rhs, preferredLanguageIdentifier: key) {
                return languageMatchRank(for: lhs, preferredLanguageIdentifier: key)
                    < languageMatchRank(for: rhs, preferredLanguageIdentifier: key)
            }
            if siriRank(for: lhs) != siriRank(for: rhs) {
                return siriRank(for: lhs) < siriRank(for: rhs)
            }
            if qualityRank(for: lhs) != qualityRank(for: rhs) {
                return qualityRank(for: lhs) < qualityRank(for: rhs)
            }
            if familyRank(for: lhs) != familyRank(for: rhs) {
                return familyRank(for: lhs) < familyRank(for: rhs)
            }
            return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
        }

        let options = rankedVoices.map { voice in
            let resolvedLabel = labelsByIdentifier[voice.identifier] ?? label(for: voice)
            labelsByIdentifier[voice.identifier] = resolvedLabel
            return SpeechVoiceOption(id: voice.identifier, title: resolvedLabel)
        }

        let automaticTitle: String
        if let firstVoice = rankedVoices.first {
            automaticTitle = "Automatic (\(shortLabel(for: firstVoice)))"
        } else {
            automaticTitle = "Automatic"
        }

        let cached = CachedLanguageData(
            rankedVoices: rankedVoices,
            options: options,
            automaticTitle: automaticTitle,
            bestVoiceIdentifier: rankedVoices.first?.identifier
        )
        cachedLanguageData[key] = cached
        return cached
    }

    private static func shouldInclude(_ voice: AVSpeechSynthesisVoice) -> Bool {
        !voice.voiceTraits.contains(.isNoveltyVoice)
    }

    private static func label(for voice: AVSpeechSynthesisVoice) -> String {
        let localeLabel = Locale.current.localizedString(forIdentifier: voice.language) ?? voice.language
        if let descriptor = descriptorLabel(for: voice) {
            return "\(voice.name) • \(localeLabel) • \(descriptor)"
        }
        return "\(voice.name) • \(localeLabel)"
    }

    private static func shortLabel(for voice: AVSpeechSynthesisVoice) -> String {
        if let descriptor = descriptorLabel(for: voice) {
            return "\(voice.name) • \(descriptor)"
        }
        return voice.name
    }

    private static func descriptorLabel(for voice: AVSpeechSynthesisVoice) -> String? {
        if voice.voiceTraits.contains(.isPersonalVoice) {
            return "Personal"
        }
        switch voice.quality {
        case .premium:
            return "Premium"
        case .enhanced:
            return "Enhanced"
        default:
            let identifier = voice.identifier.lowercased()
            if identifier.contains("eloquence") {
                return "Eloquence"
            }
            if identifier.contains("super-compact") || identifier.contains("compact") {
                return "Compact"
            }
            return nil
        }
    }

    private static func cleanedIdentifier(_ identifier: String?) -> String {
        identifier?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private static func languageMatchRank(
        for voice: AVSpeechSynthesisVoice,
        preferredLanguageIdentifier: String
    ) -> Int {
        if voice.language.caseInsensitiveCompare(preferredLanguageIdentifier) == .orderedSame {
            return 0
        }
        if normalizedLanguageCode(from: voice.language) == normalizedLanguageCode(from: preferredLanguageIdentifier) {
            return 1
        }
        return 2
    }

    private static func siriRank(for voice: AVSpeechSynthesisVoice) -> Int {
        if isSiriOptionTwoCandidate(voice) {
            return 0
        }
        if isSiriVoice(voice) {
            return 1
        }
        return 2
    }

    private static func isSiriOptionTwoCandidate(_ voice: AVSpeechSynthesisVoice) -> Bool {
        let searchable = "\(voice.name) \(voice.identifier)".lowercased()
        guard searchable.contains("siri") else {
            return false
        }
        return searchable.contains("voice 2")
            || searchable.contains("option 2")
            || searchable.contains("siri 2")
            || searchable.contains(".2")
            || searchable.contains("_2")
            || searchable.contains("-2")
    }

    private static func isSiriVoice(_ voice: AVSpeechSynthesisVoice) -> Bool {
        let searchable = "\(voice.name) \(voice.identifier)".lowercased()
        return searchable.contains("siri")
    }

    private static func qualityRank(for voice: AVSpeechSynthesisVoice) -> Int {
        switch voice.quality {
        case .premium:
            return 0
        case .enhanced:
            return 1
        default:
            return 2
        }
    }

    private static func familyRank(for voice: AVSpeechSynthesisVoice) -> Int {
        let identifier = voice.identifier.lowercased()
        if identifier.contains("eloquence") {
            return 2
        }
        if identifier.contains("super-compact") {
            return 1
        }
        return 0
    }

    private static func normalizedLanguageCode(from identifier: String) -> String {
        let normalizedIdentifier = identifier.replacingOccurrences(of: "_", with: "-")
        let locale = Locale(identifier: normalizedIdentifier)
        if let languageCode = locale.language.languageCode?.identifier {
            return languageCode.lowercased()
        }
        return normalizedIdentifier
            .split(separator: "-")
            .first
            .map { String($0).lowercased() } ?? normalizedIdentifier.lowercased()
    }
}

@MainActor
final class VoicePlaybackController: NSObject, ObservableObject, @preconcurrency AVSpeechSynthesizerDelegate {
    @Published private(set) var isSpeaking = false

    private let synthesizer = AVSpeechSynthesizer()

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(
        _ text: String,
        preferredVoiceIdentifier: String?,
        preferredLanguageIdentifier: String
    ) {
        stop()
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = 0.48
        utterance.voice = SpeechVoiceCatalog.resolveVoice(
            preferredIdentifier: preferredVoiceIdentifier,
            preferredLanguageIdentifier: preferredLanguageIdentifier
        )
        synthesizer.speak(utterance)
        isSpeaking = true
    }

    func stop() {
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        isSpeaking = false
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        isSpeaking = false
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        isSpeaking = false
    }
}
