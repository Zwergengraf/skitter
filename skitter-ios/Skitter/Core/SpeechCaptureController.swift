import AVFoundation
import Speech

@MainActor
final class SpeechCaptureController: NSObject, ObservableObject {
    enum AuthorizationState: Equatable {
        case unknown
        case authorized
        case denied
        case restricted
        case unavailable

        var label: String {
            switch self {
            case .unknown:
                return "Not requested"
            case .authorized:
                return "Authorized"
            case .denied:
                return "Denied"
            case .restricted:
                return "Restricted"
            case .unavailable:
                return "Unavailable"
            }
        }
    }

    @Published private(set) var authorizationState: AuthorizationState = .unknown
    @Published private(set) var isListening = false
    @Published private(set) var isPreparing = false
    @Published private(set) var transcript: String = ""
    @Published private(set) var audioLevel: Double = 0
    @Published var statusText: String = "Ready"
    @Published var errorText: String?

    private var audioEngine = AVAudioEngine()
    private var recognitionLocaleIdentifier: String
    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var silenceTask: Task<Void, Never>?
    private var onTranscript: ((String) -> Void)?
    private var onSegment: ((String) async -> Void)?
    private var silenceInterval: TimeInterval = 1.2
    private var autoSubmitOnSilence = false
    private var currentRecognitionSessionID = UUID()
    private var ignoredRecognitionSessionIDs: Set<UUID> = []

    init(locale: Locale = .current) {
        self.recognitionLocaleIdentifier = locale.identifier
        self.speechRecognizer = SFSpeechRecognizer(locale: locale)
        super.init()
    }

    func startListening(
        silenceInterval: TimeInterval,
        autoSubmitOnSilence: Bool,
        onTranscript: @escaping (String) -> Void,
        onSegment: ((String) async -> Void)? = nil
    ) async {
        guard !isListening, !isPreparing else { return }

        self.onTranscript = onTranscript
        self.onSegment = onSegment
        self.silenceInterval = silenceInterval
        self.autoSubmitOnSilence = autoSubmitOnSilence
        self.errorText = nil
        self.statusText = "Preparing microphone..."
        self.isPreparing = true

        do {
            prepareForNewRecognitionSession()
            try await ensurePermissions()
            try configureAudioSession()
            try startRecognitionSession()
            self.isPreparing = false
            self.isListening = true
            self.statusText = autoSubmitOnSilence ? "Listening for your next prompt..." : "Listening..."
        } catch {
            self.isPreparing = false
            self.isListening = false
            self.statusText = "Voice unavailable"
            self.errorText = error.localizedDescription
        }
    }

    func setRecognitionLocaleIdentifier(_ identifier: String) {
        let cleaned = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedIdentifier = cleaned.isEmpty ? Locale.current.identifier : cleaned
        let locale = Locale(identifier: resolvedIdentifier)
        recognitionLocaleIdentifier = locale.identifier

        if speechRecognizer?.locale.identifier == locale.identifier {
            return
        }

        if isListening || isPreparing {
            stopListening(clearTranscript: false)
        }

        speechRecognizer = SFSpeechRecognizer(locale: locale)
        if speechRecognizer == nil {
            authorizationState = .unavailable
            statusText = "Voice unavailable"
            errorText = "Speech recognition is not available for \(locale.localizedString(forIdentifier: resolvedIdentifier) ?? resolvedIdentifier)."
        } else if errorText != nil {
            errorText = nil
            statusText = "Ready"
        }
    }

    func stopListening(clearTranscript: Bool = false) {
        silenceTask?.cancel()
        silenceTask = nil

        ignoredRecognitionSessionIDs.insert(currentRecognitionSessionID)
        recognitionRequest?.endAudio()

        if audioEngine.isRunning {
            audioEngine.stop()
        }

        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = nil
        audioEngine.reset()
        audioEngine = AVAudioEngine()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        isListening = false
        isPreparing = false
        audioLevel = 0
        if clearTranscript {
            transcript = ""
            onTranscript?("")
        }
        if errorText == nil {
            statusText = clearTranscript ? "Ready" : "Paused"
        }
    }

    func submitCurrentTranscript() {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        stopListening(clearTranscript: true)
        statusText = "Sending..."
        Task { [weak self] in
            await self?.onSegment?(text)
            await MainActor.run {
                self?.statusText = "Ready"
            }
        }
    }

    private func ensurePermissions() async throws {
        let speechStatus = await requestSpeechAuthorization()
        switch speechStatus {
        case .authorized:
            authorizationState = .authorized
        case .denied:
            authorizationState = .denied
            throw SpeechCaptureError.speechPermissionDenied
        case .restricted:
            authorizationState = .restricted
            throw SpeechCaptureError.speechPermissionRestricted
        case .notDetermined:
            authorizationState = .unknown
            throw SpeechCaptureError.speechPermissionDenied
        @unknown default:
            authorizationState = .unavailable
            throw SpeechCaptureError.speechRecognizerUnavailable
        }

        let microphoneGranted = await requestMicrophoneAuthorization()
        guard microphoneGranted else {
            throw SpeechCaptureError.microphonePermissionDenied
        }

        guard let speechRecognizer, speechRecognizer.isAvailable else {
            authorizationState = .unavailable
            throw SpeechCaptureError.speechRecognizerUnavailable
        }
    }

    private func configureAudioSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker, .allowBluetoothHFP])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
    }

    private func startRecognitionSession() throws {
        guard let speechRecognizer else {
            throw SpeechCaptureError.speechRecognizerUnavailable
        }

        let sessionID = UUID()
        currentRecognitionSessionID = sessionID

        transcript = ""
        onTranscript?("")

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        recognitionRequest = request

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            guard let self else { return }
            self.recognitionRequest?.append(buffer)
            self.updateAudioLevel(from: buffer)
        }

        audioEngine.prepare()
        try audioEngine.start()

        recognitionTask = speechRecognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                if self.ignoredRecognitionSessionIDs.contains(sessionID) {
                    return
                }

                if let result {
                    let text = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.transcript = text
                    self.onTranscript?(text)
                    if self.autoSubmitOnSilence {
                        self.scheduleSilenceSubmission()
                    }
                    if result.isFinal {
                        if self.autoSubmitOnSilence {
                            self.submitCurrentTranscript()
                        } else {
                            self.statusText = text.isEmpty ? "Listening..." : "Transcript ready"
                        }
                    }
                }

                if let error {
                    if Self.shouldIgnoreRecognizerError(error) {
                        return
                    }
                    self.errorText = error.localizedDescription
                    self.statusText = "Voice unavailable"
                    self.stopListening(clearTranscript: false)
                }
            }
        }
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

    private func prepareForNewRecognitionSession() {
        let locale = Locale(identifier: recognitionLocaleIdentifier)
        speechRecognizer = SFSpeechRecognizer(locale: locale)
        recognitionTask = nil
        recognitionRequest = nil
        audioLevel = 0
        audioEngine.reset()
        audioEngine = AVAudioEngine()
    }

    private func scheduleSilenceSubmission() {
        silenceTask?.cancel()

        let capturedTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !capturedTranscript.isEmpty else { return }

        silenceTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: UInt64(max(0.1, self.silenceInterval) * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard self.isListening else { return }
            if self.transcript.trimmingCharacters(in: .whitespacesAndNewlines) == capturedTranscript {
                self.submitCurrentTranscript()
            }
        }
    }

    private func updateAudioLevel(from buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.floatChannelData?.pointee else {
            audioLevel = max(0, audioLevel * 0.75)
            return
        }

        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else {
            audioLevel = max(0, audioLevel * 0.75)
            return
        }

        var peak: Float = 0
        for index in 0..<frameCount {
            peak = max(peak, abs(channelData[index]))
        }
        let normalized = min(1.0, Double(peak) * 7.0)
        audioLevel = max(normalized, audioLevel * 0.68)
    }

    private func requestSpeechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func requestMicrophoneAuthorization() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }
}

private enum SpeechCaptureError: LocalizedError {
    case microphonePermissionDenied
    case speechPermissionDenied
    case speechPermissionRestricted
    case speechRecognizerUnavailable

    var errorDescription: String? {
        switch self {
        case .microphonePermissionDenied:
            return "Microphone access is required for voice input."
        case .speechPermissionDenied:
            return "Speech recognition access is required for voice input."
        case .speechPermissionRestricted:
            return "Speech recognition is restricted on this device."
        case .speechRecognizerUnavailable:
            return "Speech recognition is currently unavailable."
        }
    }
}
