import Foundation
import AVFoundation

@MainActor
final class OpenAITTSPlayer: NSObject {
    enum TTSError: LocalizedError {
        case invalidBaseURL
        case missingAPIKey
        case invalidResponse
        case http(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .invalidBaseURL:
                return "Invalid OpenAI base URL"
            case .missingAPIKey:
                return "OpenAI API key is required for TTS"
            case .invalidResponse:
                return "Invalid response from TTS server"
            case let .http(code, message):
                return "OpenAI TTS HTTP \(code): \(message)"
            case let .decoding(message):
                return "OpenAI TTS decode error: \(message)"
            }
        }
    }

    private struct SpeechBody: Encodable {
        let model: String
        let voice: String
        let input: String
        let response_format: String
    }

    private final class StreamingDelegate: NSObject, URLSessionDataDelegate, @unchecked Sendable {
        var onResponse: ((HTTPURLResponse) -> URLSession.ResponseDisposition)?
        var onData: ((Data) -> Void)?
        var onComplete: ((Error?) -> Void)?

        func urlSession(
            _ session: URLSession,
            dataTask: URLSessionDataTask,
            didReceive response: URLResponse,
            completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
        ) {
            guard let http = response as? HTTPURLResponse else {
                completionHandler(.cancel)
                onComplete?(TTSError.invalidResponse)
                return
            }
            completionHandler(onResponse?(http) ?? .allow)
        }

        func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
            onData?(data)
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            onComplete?(error)
        }
    }

    private let sessionConfiguration: URLSessionConfiguration
    private let audioEngine = AVAudioEngine()
    private let playerNode = AVAudioPlayerNode()
    private let pcmFormat: AVAudioFormat
    private let bytesPerFrame: Int
    private let framesPerBuffer: AVAudioFrameCount = 1200
    private let minFramesBeforeStart: AVAudioFrameCount = 3600

    private var streamSession: URLSession?
    private var streamTask: URLSessionDataTask?
    private var meterTimer: Timer?
    private var audioGraphPrepared = false
    private var pendingPCM = Data()
    private var queuedBufferCount = 0
    private var queuedFrames: AVAudioFrameCount = 0
    private var streamFinished = false
    private var playbackStarted = false
    private var currentLevel: Double = 0
    private var isPlaying = false

    var onPlaybackStateChange: ((Bool) -> Void)?
    var onLevelChange: ((Double) -> Void)?

    override init() {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 120
        configuration.timeoutIntervalForResource = 300
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.sessionConfiguration = configuration
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 24_000,
            channels: 1,
            interleaved: false
        ) else {
            fatalError("Unable to create PCM format")
        }
        self.pcmFormat = format
        self.bytesPerFrame = Int(format.streamDescription.pointee.mBytesPerFrame)
        super.init()
    }

    func stop() {
        cancelStreamingRequest()
        stopMetering()
        playerNode.stop()
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        pendingPCM.removeAll(keepingCapacity: false)
        queuedBufferCount = 0
        queuedFrames = 0
        streamFinished = false
        playbackStarted = false
        currentLevel = 0
        setPlaybackState(false)
        onLevelChange?(0)
    }

    func speak(
        baseURL: String,
        apiKey: String,
        model: String,
        voice: String,
        text: String
    ) async throws {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty else { return }

        let trimmedAPIKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAPIKey.isEmpty else {
            throw TTSError.missingAPIKey
        }

        stop()

        let url = try speechURL(baseURL: baseURL)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(trimmedAPIKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            SpeechBody(
                model: model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "gpt-4o-mini-tts" : model.trimmingCharacters(in: .whitespacesAndNewlines),
                voice: voice.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "alloy" : voice.trimmingCharacters(in: .whitespacesAndNewlines),
                input: trimmedText,
                response_format: "pcm"
            )
        )

        try prepareAudioEngine()
        try await streamAndPlay(request: request)
    }

    private func handlePlaybackFinished() {
        stopMetering()
        playerNode.stop()
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        pendingPCM.removeAll(keepingCapacity: false)
        queuedBufferCount = 0
        queuedFrames = 0
        streamFinished = false
        playbackStarted = false
        currentLevel = 0
        setPlaybackState(false)
        onLevelChange?(0)
    }

    private func startMetering() {
        stopMetering()
        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.decayMeterLevel()
            }
        }
        if let meterTimer {
            RunLoop.main.add(meterTimer, forMode: .common)
        }
    }

    private func stopMetering() {
        meterTimer?.invalidate()
        meterTimer = nil
    }

    private func decayMeterLevel() {
        guard isPlaying else {
            if currentLevel != 0 {
                currentLevel = 0
                onLevelChange?(0)
            }
            return
        }
        currentLevel *= 0.86
        if currentLevel < 0.004 {
            currentLevel = 0
        }
        onLevelChange?(currentLevel)
    }

    private func speechURL(baseURL: String) throws -> URL {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed), let initialBase = components.url else {
            throw TTSError.invalidBaseURL
        }
        var normalizedBase = initialBase
        if components.host?.lowercased() == "localhost" {
            components.host = "127.0.0.1"
            normalizedBase = components.url ?? normalizedBase
        }

        let lowerPath = normalizedBase.path.lowercased()
        if lowerPath.hasSuffix("/v1") {
            return normalizedBase.appendingPathComponent("audio").appendingPathComponent("speech")
        }
        return normalizedBase.appendingPathComponent("v1").appendingPathComponent("audio").appendingPathComponent("speech")
    }

    private func prepareAudioEngine() throws {
        if !audioGraphPrepared {
            audioEngine.attach(playerNode)
            audioEngine.connect(playerNode, to: audioEngine.mainMixerNode, format: pcmFormat)
            audioGraphPrepared = true
        }
        if !audioEngine.isRunning {
            try audioEngine.start()
        }
    }

    private func streamAndPlay(request: URLRequest) async throws {
        let delegate = StreamingDelegate()
        let session = URLSession(configuration: sessionConfiguration, delegate: delegate, delegateQueue: .main)
        let task = session.dataTask(with: request)
        streamSession = session
        streamTask = task

        var statusCode = 0
        var sawResponse = false
        var hasAudioData = false
        var httpErrorBody = Data()

        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                var didResume = false
                func finish(_ result: Result<Void, Error>) {
                    guard !didResume else { return }
                    didResume = true
                    continuation.resume(with: result)
                }

                delegate.onResponse = { response in
                    sawResponse = true
                    statusCode = response.statusCode
                    return .allow
                }

                delegate.onData = { [weak self] data in
                    guard let self else { return }
                    guard !data.isEmpty else { return }

                    if !(200..<300).contains(statusCode) {
                        if httpErrorBody.count < 8_192 {
                            httpErrorBody.append(data.prefix(8_192 - httpErrorBody.count))
                        }
                        return
                    }

                    hasAudioData = true
                    do {
                        try self.consumePCM(data)
                    } catch {
                        finish(.failure(error))
                        self.cancelStreamingRequest()
                    }
                }

                delegate.onComplete = { [weak self] error in
                    guard let self else { return }
                    defer {
                        session.finishTasksAndInvalidate()
                        self.streamSession = nil
                        self.streamTask = nil
                    }

                    if let error {
                        let nsError = error as NSError
                        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
                            finish(.failure(CancellationError()))
                            return
                        }
                        finish(.failure(error))
                        return
                    }

                    do {
                        guard sawResponse else {
                            throw TTSError.invalidResponse
                        }
                        guard (200..<300).contains(statusCode) else {
                            let message = String(data: httpErrorBody, encoding: .utf8) ?? "request failed"
                            throw TTSError.http(statusCode, message)
                        }
                        try self.finishPCMStream()
                        guard hasAudioData else {
                            throw TTSError.decoding("No audio data returned")
                        }
                        finish(.success(()))
                    } catch {
                        finish(.failure(error))
                    }
                }

                task.resume()
            }
        } onCancel: { [weak self] in
            task.cancel()
            session.invalidateAndCancel()
            Task { @MainActor [weak self] in
                self?.cancelStreamingRequest()
            }
        }
    }

    private func consumePCM(_ data: Data) throws {
        pendingPCM.append(data)
        let chunkBytes = Int(framesPerBuffer) * bytesPerFrame
        while pendingPCM.count >= chunkBytes {
            let chunk = pendingPCM.prefix(chunkBytes)
            try schedulePCMBuffer(chunkData: Data(chunk))
            pendingPCM.removeFirst(chunkBytes)
        }
    }

    private func finishPCMStream() throws {
        streamFinished = true
        let alignedCount = pendingPCM.count - (pendingPCM.count % bytesPerFrame)
        if alignedCount > 0 {
            let remainder = pendingPCM.prefix(alignedCount)
            try schedulePCMBuffer(chunkData: Data(remainder))
            pendingPCM.removeFirst(alignedCount)
        }
        pendingPCM.removeAll(keepingCapacity: false)

        if queuedBufferCount == 0 {
            handlePlaybackFinished()
            return
        }

        maybeStartPlayback(force: true)
    }

    private func schedulePCMBuffer(chunkData: Data) throws {
        guard !chunkData.isEmpty else { return }

        let frameCount = AVAudioFrameCount(chunkData.count / bytesPerFrame)
        guard frameCount > 0 else { return }

        guard let buffer = AVAudioPCMBuffer(pcmFormat: pcmFormat, frameCapacity: frameCount) else {
            throw TTSError.decoding("Unable to allocate audio buffer")
        }
        buffer.frameLength = frameCount
        guard let channel = buffer.int16ChannelData?[0] else {
            throw TTSError.decoding("Unable to map PCM samples")
        }
        chunkData.withUnsafeBytes { rawBuffer in
            guard let src = rawBuffer.baseAddress else { return }
            memcpy(channel, src, chunkData.count)
        }

        updateLevel(with: chunkData)
        queuedBufferCount += 1
        queuedFrames += frameCount

        playerNode.scheduleBuffer(buffer) { [weak self] in
            Task { @MainActor [weak self] in
                self?.didFinishBuffer(frameCount: frameCount)
            }
        }

        maybeStartPlayback(force: false)
    }

    private func didFinishBuffer(frameCount: AVAudioFrameCount) {
        if queuedBufferCount > 0 {
            queuedBufferCount -= 1
        }
        if queuedFrames > frameCount {
            queuedFrames -= frameCount
        } else {
            queuedFrames = 0
        }

        if streamFinished && queuedBufferCount == 0 {
            handlePlaybackFinished()
        }
    }

    private func maybeStartPlayback(force: Bool) {
        guard !playbackStarted else { return }
        if !force && queuedFrames < minFramesBeforeStart {
            return
        }
        playerNode.play()
        playbackStarted = true
        setPlaybackState(true)
        startMetering()
    }

    private func updateLevel(with pcmData: Data) {
        let level = pcmData.withUnsafeBytes { rawBuffer -> Double in
            let samples = rawBuffer.bindMemory(to: Int16.self)
            guard !samples.isEmpty else { return 0 }
            var power: Double = 0
            for sample in samples {
                let normalized = Double(sample) / 32_768.0
                power += normalized * normalized
            }
            let rms = sqrt(power / Double(samples.count))
            return min(1.0, pow(rms * 3.2, 0.85))
        }

        currentLevel = max(level, currentLevel * 0.72)
        onLevelChange?(currentLevel)
    }

    private func setPlaybackState(_ playing: Bool) {
        guard isPlaying != playing else { return }
        isPlaying = playing
        onPlaybackStateChange?(playing)
    }

    private func cancelStreamingRequest() {
        streamTask?.cancel()
        streamTask = nil
        streamSession?.invalidateAndCancel()
        streamSession = nil
        playerNode.stop()
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        streamFinished = false
        pendingPCM.removeAll(keepingCapacity: false)
        queuedBufferCount = 0
        queuedFrames = 0
        playbackStarted = false
        currentLevel = 0
        onLevelChange?(0)
        setPlaybackState(false)
        stopMetering()
    }

    deinit {
        meterTimer?.invalidate()
    }
}
