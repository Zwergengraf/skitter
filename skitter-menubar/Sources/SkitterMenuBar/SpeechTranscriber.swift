import Foundation
import WhisperKit

enum SpeechTranscriberError: LocalizedError {
    case microphonePermissionDenied
    case unavailable
    case modelNotDownloaded(String)
    case noAudioInput

    var errorDescription: String? {
        switch self {
        case .microphonePermissionDenied:
            return "Microphone permission was denied."
        case .unavailable:
            return "Local Whisper transcription is unavailable."
        case let .modelNotDownloaded(model):
            return "Whisper model '\(model)' is not downloaded. Open Settings and download it first."
        case .noAudioInput:
            return "Microphone started, but no audio input was detected."
        }
    }
}

final class SpeechTranscriber {
    private var whisperKit: WhisperKit?
    private var loadedModelName: String?
    private var loadedModelFolderPath: String?
    private var captureTask: Task<Void, Never>?
    private var decodeTask: Task<Void, Never>?
    private var streamContinuation: AsyncThrowingStream<[Float], Error>.Continuation?

    private let audioQueue = DispatchQueue(label: "io.skitter.menubar.audio", qos: .userInitiated)
    private var capturedSamples: [Float] = []
    private var lastProcessedSampleCount: Int = 0
    private var lastSpeechActivityUptimeNanos: UInt64 = 0
    private var noiseFloorMeanAbs: Float = 0
    private var hasNoiseFloorEstimate = false
    private var transcriptionInFlight = false
    private var latestText: String = ""
    private var isStreaming = false

    func requestMicrophonePermission() async throws {
        let granted = await AudioProcessor.requestRecordPermission()
        if !granted {
            throw SpeechTranscriberError.microphonePermissionDenied
        }
    }

    func startStreaming(
        modelName: String,
        modelFolderPath: String?,
        failOnNoAudio: Bool = true,
        onStatus: (@MainActor (String) -> Void)? = nil,
        onPartial: @escaping @MainActor (String) -> Void,
        onError: @escaping @MainActor (Error) -> Void
    ) async throws {
        cancelRecording()

        await onStatus?("Preparing local Whisper…")
        let whisper = try await loadWhisperKitIfNeeded(modelName: modelName, modelFolderPath: modelFolderPath)
        if whisper.modelState != .loaded {
            await onStatus?("Loading local Whisper model (\(modelName))…")
            do {
                try await whisper.loadModels()
            } catch {
                if isModelUnavailable(error) {
                    throw SpeechTranscriberError.modelNotDownloaded(modelName.trimmingCharacters(in: .whitespacesAndNewlines))
                }
                throw error
            }
        }
        try await whisper.loadTokenizerIfNeeded()
        try await requestMicrophonePermission()

        latestText = ""
        capturedSamples = []
        lastProcessedSampleCount = 0
        lastSpeechActivityUptimeNanos = 0
        noiseFloorMeanAbs = 0
        hasNoiseFloorEstimate = false
        transcriptionInFlight = false

        let (stream, continuation) = whisper.audioProcessor.startStreamingRecordingLive()
        streamContinuation = continuation
        isStreaming = true
        await onStatus?("Listening…")

        captureTask = Task { [weak self] in
            guard let self else { return }
            do {
                for try await chunk in stream {
                    if Task.isCancelled || !self.isStreaming {
                        break
                    }
                    self.appendSamples(chunk)
                }
            } catch {
                if !Task.isCancelled && self.isStreaming {
                    await onError(error)
                }
            }
        }

        decodeTask = Task { [weak self] in
            guard let self else { return }
            var emptyAudioTicks = 0
            while self.isStreaming && !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 700_000_000)
                let hasSamples = self.audioQueue.sync { !self.capturedSamples.isEmpty }
                if !hasSamples {
                    emptyAudioTicks += 1
                    if failOnNoAudio, emptyAudioTicks >= 8 {
                        self.isStreaming = false
                        self.streamContinuation?.finish()
                        self.streamContinuation = nil
                        self.whisperKit?.audioProcessor.stopRecording()
                        await onError(SpeechTranscriberError.noAudioInput)
                        return
                    }
                } else {
                    emptyAudioTicks = 0
                }
                await self.transcribeIfNeeded(
                    whisper: whisper,
                    force: false,
                    onPartial: onPartial,
                    onError: onError
                )
            }
        }
    }

    func stopStreaming() async throws -> String {
        guard isStreaming || captureTask != nil || decodeTask != nil else {
            return latestText.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        isStreaming = false
        streamContinuation?.finish()
        streamContinuation = nil

        captureTask?.cancel()
        decodeTask?.cancel()
        captureTask = nil
        decodeTask = nil
        whisperKit?.audioProcessor.stopRecording()

        if let whisperKit {
            await transcribeIfNeeded(whisper: whisperKit, force: true, onPartial: nil, onError: nil)
        }
        return latestText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func cancelRecording() {
        isStreaming = false
        streamContinuation?.finish()
        streamContinuation = nil

        captureTask?.cancel()
        decodeTask?.cancel()
        captureTask = nil
        decodeTask = nil

        whisperKit?.audioProcessor.stopRecording()

        latestText = ""
        capturedSamples = []
        lastProcessedSampleCount = 0
        lastSpeechActivityUptimeNanos = 0
        noiseFloorMeanAbs = 0
        hasNoiseFloorEstimate = false
        transcriptionInFlight = false
    }

    func resetStreamingBuffer() {
        audioQueue.async { [self] in
            self.capturedSamples.removeAll(keepingCapacity: true)
            self.lastProcessedSampleCount = 0
        }
        latestText = ""
    }

    func hasRecentSpeechActivity(within seconds: Double) -> Bool {
        let windowSeconds = max(0, seconds)
        if windowSeconds == 0 {
            return false
        }
        let windowNanos = UInt64((windowSeconds * 1_000_000_000).rounded())
        return audioQueue.sync {
            guard lastSpeechActivityUptimeNanos > 0 else { return false }
            let now = DispatchTime.now().uptimeNanoseconds
            let elapsed = now >= lastSpeechActivityUptimeNanos
                ? now - lastSpeechActivityUptimeNanos
                : 0
            return elapsed <= windowNanos
        }
    }

    private func appendSamples(_ chunk: [Float]) {
        audioQueue.async {
            self.registerSpeechActivity(chunk)
            self.capturedSamples.append(contentsOf: chunk)
            let maxSamples = WhisperKit.sampleRate * 120
            if self.capturedSamples.count > maxSamples {
                let removeCount = self.capturedSamples.count - maxSamples
                self.capturedSamples.removeFirst(removeCount)
                self.lastProcessedSampleCount = max(0, self.lastProcessedSampleCount - removeCount)
            }
        }
    }

    private func registerSpeechActivity(_ chunk: [Float]) {
        guard !chunk.isEmpty else { return }

        var sumAbs: Float = 0
        var peakAbs: Float = 0
        for sample in chunk {
            let magnitude = Swift.abs(sample)
            sumAbs += magnitude
            if magnitude > peakAbs {
                peakAbs = magnitude
            }
        }

        let meanAbs = sumAbs / Float(chunk.count)
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

        // Adapt noise floor only from quiet chunks, so speech does not raise the silence baseline.
        let alpha: Float = 0.04
        noiseFloorMeanAbs = ((1 - alpha) * noiseFloorMeanAbs) + (alpha * meanAbs)
    }

    private func loadWhisperKitIfNeeded(modelName: String, modelFolderPath: String?) async throws -> WhisperKit {
        let normalizedModel = modelName.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedFolder = modelFolderPath?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let whisperKit, loadedModelName == normalizedModel, loadedModelFolderPath == normalizedFolder {
            return whisperKit
        }

        if let whisperKit {
            await whisperKit.unloadModels()
            whisperKit.clearState()
            self.whisperKit = nil
            loadedModelName = nil
            loadedModelFolderPath = nil
        }

        let config = WhisperKitConfig(
            model: normalizedModel.isEmpty ? nil : normalizedModel,
            modelFolder: normalizedFolder,
            verbose: false,
            load: true,
            download: false
        )
        let instance: WhisperKit
        do {
            instance = try await WhisperKit(config)
        } catch {
            if isModelUnavailable(error) {
                throw SpeechTranscriberError.modelNotDownloaded(normalizedModel.isEmpty ? "tiny" : normalizedModel)
            }
            throw error
        }
        whisperKit = instance
        loadedModelName = normalizedModel.isEmpty ? "tiny" : normalizedModel
        loadedModelFolderPath = normalizedFolder
        return instance
    }

    private func isModelUnavailable(_ error: Error) -> Bool {
        let message = error.localizedDescription.lowercased()
        return message.contains("models unavailable")
            || message.contains("no models found")
            || message.contains("model not found")
            || message.contains("model folder is not set")
    }

    private func transcribeIfNeeded(
        whisper: WhisperKit,
        force: Bool,
        onPartial: (@MainActor (String) -> Void)?,
        onError: (@MainActor (Error) -> Void)?
    ) async {
        if transcriptionInFlight {
            return
        }

        let snapshot: (samples: [Float], totalCount: Int) = audioQueue.sync {
            let total = capturedSamples.count
            let start = max(0, total - (WhisperKit.sampleRate * 25))
            return (Array(capturedSamples[start..<total]), total)
        }
        if snapshot.samples.count < WhisperKit.sampleRate {
            return
        }
        if !force, snapshot.totalCount - lastProcessedSampleCount < WhisperKit.sampleRate / 2 {
            return
        }
        if force, snapshot.totalCount <= lastProcessedSampleCount {
            return
        }

        transcriptionInFlight = true
        defer {
            transcriptionInFlight = false
        }

        let decode = DecodingOptions(task: .transcribe, withoutTimestamps: true, concurrentWorkerCount: 1)
        do {
            let results = try await whisper.transcribe(audioArray: snapshot.samples, decodeOptions: decode)
            lastProcessedSampleCount = snapshot.totalCount
            let merged = results
                .map(\.text)
                .joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if merged.isEmpty {
                return
            }
            if merged == latestText {
                return
            }
            latestText = merged
            if let onPartial {
                await onPartial(merged)
            }
        } catch {
            if isStreaming, let onError {
                await onError(error)
            }
        }
    }
}
