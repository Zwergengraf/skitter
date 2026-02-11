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
    private var captureTask: Task<Void, Never>?
    private var decodeTask: Task<Void, Never>?
    private var streamContinuation: AsyncThrowingStream<[Float], Error>.Continuation?

    private let audioQueue = DispatchQueue(label: "io.skittermander.menubar.audio", qos: .userInitiated)
    private var capturedSamples: [Float] = []
    private var lastProcessedSampleCount: Int = 0
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
        onStatus: (@MainActor (String) -> Void)? = nil,
        onPartial: @escaping @MainActor (String) -> Void,
        onError: @escaping @MainActor (Error) -> Void
    ) async throws {
        cancelRecording()

        await onStatus?("Loading local Whisper model (\(modelName))…")
        let whisper = try await loadWhisperKitIfNeeded(modelName: modelName)
        if whisper.modelState != .loaded {
            try await whisper.loadModels()
        }
        try await whisper.loadTokenizerIfNeeded()
        try await requestMicrophonePermission()

        latestText = ""
        capturedSamples = []
        lastProcessedSampleCount = 0
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
                if !Task.isCancelled {
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
                    if emptyAudioTicks >= 8 {
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
        transcriptionInFlight = false
    }

    private func appendSamples(_ chunk: [Float]) {
        audioQueue.async {
            self.capturedSamples.append(contentsOf: chunk)
            let maxSamples = WhisperKit.sampleRate * 120
            if self.capturedSamples.count > maxSamples {
                let removeCount = self.capturedSamples.count - maxSamples
                self.capturedSamples.removeFirst(removeCount)
                self.lastProcessedSampleCount = max(0, self.lastProcessedSampleCount - removeCount)
            }
        }
    }

    private func loadWhisperKitIfNeeded(modelName: String) async throws -> WhisperKit {
        let normalizedModel = modelName.trimmingCharacters(in: .whitespacesAndNewlines)
        if let whisperKit, loadedModelName == normalizedModel {
            return whisperKit
        }

        if let whisperKit, loadedModelName != normalizedModel {
            await whisperKit.unloadModels()
            whisperKit.clearState()
            self.whisperKit = nil
            loadedModelName = nil
        }

        let config = WhisperKitConfig(
            model: normalizedModel.isEmpty ? nil : normalizedModel,
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
        return instance
    }

    private func isModelUnavailable(_ error: Error) -> Bool {
        let message = error.localizedDescription.lowercased()
        return message.contains("models unavailable")
            || message.contains("no models found")
            || message.contains("model not found")
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
            latestText = merged
            if let onPartial {
                await onPartial(merged)
            }
        } catch {
            if let onError {
                await onError(error)
            }
        }
    }
}
