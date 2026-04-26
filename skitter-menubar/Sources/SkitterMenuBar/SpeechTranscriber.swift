import AVFoundation
import Foundation
import Speech

enum SpeechTranscriberError: LocalizedError {
    case microphonePermissionDenied
    case speechPermissionDenied
    case speechPermissionRestricted
    case recognizerUnavailable
    case localeUnsupported(String)
    case onDeviceRecognitionUnavailable(String)
    case noAudioInput

    var errorDescription: String? {
        switch self {
        case .microphonePermissionDenied:
            return "Microphone permission was denied."
        case .speechPermissionDenied:
            return "Speech recognition permission was denied."
        case .speechPermissionRestricted:
            return "Speech recognition is restricted on this Mac."
        case .recognizerUnavailable:
            return "Apple speech recognition is currently unavailable."
        case let .localeUnsupported(locale):
            return "Apple speech recognition does not support \(locale)."
        case let .onDeviceRecognitionUnavailable(locale):
            return "On-device speech recognition is not available for \(locale). Disable on-device-only recognition or choose another language."
        case .noAudioInput:
            return "Microphone started, but no audio input was detected."
        }
    }
}

@MainActor
final class SpeechTranscriber {
    private var audioEngine = AVAudioEngine()
    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var noAudioTask: Task<Void, Never>?

    private var latestText: String = ""
    private var latestRawTranscript: String = ""
    private var accumulatedTranscript: String = ""
    private var ignoredTranscriptPrefix: String = ""
    private var lastSpeechActivityUptimeNanos: UInt64 = 0
    private var lastAudioInputUptimeNanos: UInt64 = 0
    private var noiseFloorMeanAbs: Float = 0
    private var hasNoiseFloorEstimate = false
    private var isStreaming = false
    private var isTearingDown = false

    private var activeLocaleIdentifier: String = ""
    private var activeRequiresOnDeviceRecognition = false
    private var activeFailOnNoAudio = true
    private var activeOnStatus: (@MainActor (String) -> Void)?
    private var activeOnPartial: (@MainActor (String) -> Void)?
    private var activeOnError: (@MainActor (Error) -> Void)?

    func requestMicrophonePermission() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            if !granted {
                throw SpeechTranscriberError.microphonePermissionDenied
            }
        case .denied, .restricted:
            throw SpeechTranscriberError.microphonePermissionDenied
        @unknown default:
            throw SpeechTranscriberError.microphonePermissionDenied
        }
    }

    func startStreaming(
        localeIdentifier: String,
        requiresOnDeviceRecognition: Bool,
        failOnNoAudio: Bool = true,
        onStatus: (@MainActor (String) -> Void)? = nil,
        onPartial: @escaping @MainActor (String) -> Void,
        onError: @escaping @MainActor (Error) -> Void
    ) async throws {
        cancelRecording()

        activeLocaleIdentifier = localeIdentifier
        activeRequiresOnDeviceRecognition = requiresOnDeviceRecognition
        activeFailOnNoAudio = failOnNoAudio
        activeOnStatus = onStatus
        activeOnPartial = onPartial
        activeOnError = onError

        onStatus?("Preparing Apple Speech...")
        try await requestSpeechRecognitionPermission()
        try await requestMicrophonePermission()

        latestText = ""
        latestRawTranscript = ""
        accumulatedTranscript = ""
        ignoredTranscriptPrefix = ""
        lastSpeechActivityUptimeNanos = 0
        lastAudioInputUptimeNanos = 0
        noiseFloorMeanAbs = 0
        hasNoiseFloorEstimate = false
        isStreaming = true

        try startRecognitionSession(clearTranscript: true)
        onStatus?("Listening...")
    }

    func stopStreaming() async throws -> String {
        guard isStreaming || recognitionTask != nil || audioEngine.isRunning else {
            return latestText.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        stopAudioAndRecognition(cancelTask: false)
        clearActiveCallbacks()
        return latestText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func cancelRecording() {
        stopAudioAndRecognition(cancelTask: true)
        clearActiveCallbacks()
        latestText = ""
        latestRawTranscript = ""
        accumulatedTranscript = ""
        ignoredTranscriptPrefix = ""
        lastSpeechActivityUptimeNanos = 0
        lastAudioInputUptimeNanos = 0
        noiseFloorMeanAbs = 0
        hasNoiseFloorEstimate = false
    }

    func resetStreamingBuffer() {
        accumulatedTranscript = ""
        ignoredTranscriptPrefix = latestRawTranscript
        latestText = ""
        lastSpeechActivityUptimeNanos = 0
    }

    func hasRecentSpeechActivity(within seconds: Double) -> Bool {
        let windowSeconds = max(0, seconds)
        if windowSeconds == 0 {
            return false
        }
        let windowNanos = UInt64((windowSeconds * 1_000_000_000).rounded())
        guard lastSpeechActivityUptimeNanos > 0 else { return false }
        let now = DispatchTime.now().uptimeNanoseconds
        let elapsed = now >= lastSpeechActivityUptimeNanos
            ? now - lastSpeechActivityUptimeNanos
            : 0
        return elapsed <= windowNanos
    }

    private func requestSpeechRecognitionPermission() async throws {
        let status = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }

        switch status {
        case .authorized:
            return
        case .denied:
            throw SpeechTranscriberError.speechPermissionDenied
        case .restricted:
            throw SpeechTranscriberError.speechPermissionRestricted
        case .notDetermined:
            throw SpeechTranscriberError.speechPermissionDenied
        @unknown default:
            throw SpeechTranscriberError.recognizerUnavailable
        }
    }

    private func startRecognitionSession(clearTranscript: Bool) throws {
        stopAudioAndRecognition(cancelTask: true, preserveStreamingFlag: true)

        let localeIdentifier = resolveLocaleIdentifier(activeLocaleIdentifier)
        let locale = Locale(identifier: localeIdentifier)
        guard let recognizer = SFSpeechRecognizer(locale: locale) else {
            throw SpeechTranscriberError.localeUnsupported(localeIdentifier)
        }
        guard recognizer.isAvailable else {
            throw SpeechTranscriberError.recognizerUnavailable
        }
        if activeRequiresOnDeviceRecognition && !recognizer.supportsOnDeviceRecognition {
            throw SpeechTranscriberError.onDeviceRecognitionUnavailable(localeIdentifier)
        }

        speechRecognizer = recognizer

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.requiresOnDeviceRecognition = activeRequiresOnDeviceRecognition
        recognitionRequest = request

        if clearTranscript {
            latestText = ""
            latestRawTranscript = ""
            accumulatedTranscript = ""
            ignoredTranscriptPrefix = ""
        }

        audioEngine = AVAudioEngine()
        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self, request] buffer, _ in
            request.append(buffer)
            Task { @MainActor [weak self] in
                self?.registerAudioActivity(buffer)
            }
        }

        audioEngine.prepare()
        try audioEngine.start()
        startNoAudioWatchdog()

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                self.handleRecognitionUpdate(result: result, error: error)
            }
        }
    }

    private func handleRecognitionUpdate(result: SFSpeechRecognitionResult?, error: Error?) {
        if let result {
            let raw = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
            latestRawTranscript = raw
            let text = combinedTranscript(currentSessionText: transcriptAfterReset(from: raw))
            latestText = text
            activeOnPartial?(text)

            if result.isFinal && isStreaming && !isTearingDown {
                accumulatedTranscript = text
                latestRawTranscript = ""
                ignoredTranscriptPrefix = ""
                restartAfterFinalResult()
            }
        }

        if let error {
            guard !isTearingDown else { return }
            if Self.shouldIgnoreRecognizerError(error) {
                return
            }
            let onError = activeOnError
            cancelRecording()
            onError?(error)
        }
    }

    private func transcriptAfterReset(from raw: String) -> String {
        let trimmedPrefix = ignoredTranscriptPrefix.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPrefix.isEmpty else {
            return raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard raw.hasPrefix(trimmedPrefix) else {
            return raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let suffixStart = raw.index(raw.startIndex, offsetBy: trimmedPrefix.count)
        return String(raw[suffixStart...]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func combinedTranscript(currentSessionText: String) -> String {
        joinTranscript(accumulatedTranscript, currentSessionText)
    }

    private func joinTranscript(_ lhs: String, _ rhs: String) -> String {
        let left = lhs.trimmingCharacters(in: .whitespacesAndNewlines)
        let right = rhs.trimmingCharacters(in: .whitespacesAndNewlines)
        if left.isEmpty { return right }
        if right.isEmpty { return left }
        if left.last?.isWhitespace == true || right.first?.isWhitespace == true {
            return left + right
        }
        if usesCJKSpacing(left.last) || usesCJKSpacing(right.first) {
            return left + right
        }
        return left + " " + right
    }

    private func usesCJKSpacing(_ character: Character?) -> Bool {
        guard let scalar = character?.unicodeScalars.first else { return false }
        switch scalar.value {
        case 0x3040...0x30FF, 0x3400...0x4DBF, 0x4E00...0x9FFF, 0xAC00...0xD7AF:
            return true
        default:
            return false
        }
    }

    private func restartAfterFinalResult() {
        guard isStreaming else { return }
        ignoredTranscriptPrefix = ""
        do {
            try startRecognitionSession(clearTranscript: false)
            activeOnStatus?("Listening...")
        } catch {
            let onError = activeOnError
            cancelRecording()
            onError?(error)
        }
    }

    private func startNoAudioWatchdog() {
        noAudioTask?.cancel()
        guard activeFailOnNoAudio else { return }
        noAudioTask = Task { [weak self] in
            var emptyAudioTicks = 0
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 700_000_000)
                guard !Task.isCancelled else { return }
                guard let self else { return }
                guard self.isStreaming else { return }
                if self.lastAudioInputUptimeNanos == 0 {
                    emptyAudioTicks += 1
                } else {
                    emptyAudioTicks = 0
                }
                if emptyAudioTicks >= 8 {
                    let onError = self.activeOnError
                    self.cancelRecording()
                    onError?(SpeechTranscriberError.noAudioInput)
                    return
                }
            }
        }
    }

    private func registerAudioActivity(_ buffer: AVAudioPCMBuffer) {
        lastAudioInputUptimeNanos = DispatchTime.now().uptimeNanoseconds
        guard let channelData = buffer.floatChannelData?.pointee else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }

        var sumAbs: Float = 0
        var peakAbs: Float = 0
        for index in 0..<frameCount {
            let magnitude = Swift.abs(channelData[index])
            sumAbs += magnitude
            if magnitude > peakAbs {
                peakAbs = magnitude
            }
        }

        let meanAbs = sumAbs / Float(frameCount)
        if !hasNoiseFloorEstimate {
            noiseFloorMeanAbs = meanAbs
            hasNoiseFloorEstimate = true
        }

        let baseline = max(noiseFloorMeanAbs, 0.0007)
        let speechMeanThreshold = max(0.0022, baseline * 3.2)
        let speechPeakThreshold = max(0.016, baseline * 10.0)
        let isSpeech = meanAbs >= speechMeanThreshold || peakAbs >= speechPeakThreshold
        if isSpeech {
            lastSpeechActivityUptimeNanos = DispatchTime.now().uptimeNanoseconds
            return
        }

        let alpha: Float = 0.04
        noiseFloorMeanAbs = ((1 - alpha) * noiseFloorMeanAbs) + (alpha * meanAbs)
    }

    private func stopAudioAndRecognition(cancelTask: Bool, preserveStreamingFlag: Bool = false) {
        isTearingDown = true
        if !preserveStreamingFlag {
            isStreaming = false
        }
        noAudioTask?.cancel()
        noAudioTask = nil

        recognitionRequest?.endAudio()
        if cancelTask {
            recognitionTask?.cancel()
        } else {
            recognitionTask?.finish()
        }
        recognitionTask = nil
        recognitionRequest = nil

        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.reset()
        isTearingDown = false
    }

    private func clearActiveCallbacks() {
        activeOnStatus = nil
        activeOnPartial = nil
        activeOnError = nil
    }

    private func resolveLocaleIdentifier(_ identifier: String) -> String {
        let cleaned = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            return Locale.current.identifier
        }
        return cleaned
    }

    private static func shouldIgnoreRecognizerError(_ error: Error) -> Bool {
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
            return true
        }
        if nsError.domain == "kAFAssistantErrorDomain" && nsError.code == 216 {
            return true
        }
        let description = nsError.localizedDescription.lowercased()
        if description.contains("request was canceled") || description.contains("request was cancelled") {
            return true
        }
        return false
    }
}
