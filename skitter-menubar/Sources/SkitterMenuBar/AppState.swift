import Foundation
import AppKit
import os
import WhisperKit

struct LocalCommand: Identifiable {
    let id: String
    let name: String
    let usage: String
    let description: String
}

@MainActor
final class AppState: ObservableObject {
    nonisolated private static let perfLogger = Logger(
        subsystem: "io.skitter.menubar",
        category: "performance"
    )

    @Published private(set) var health: HealthState = .checking
    @Published private(set) var activity: ActivityState = .idle
    @Published private(set) var contextTokens: Int = 0
    @Published private(set) var contextProgress: Double = 0
    @Published private(set) var sessionCost: Double = 0
    @Published private(set) var totalTokens: Int = 0
    @Published private(set) var modelName: String = "default"
    @Published private(set) var availableModels: [String] = []
    @Published private(set) var sessionID: String?
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var chatOpenSignal: Int = 0
    @Published private(set) var progressStatusText: String = ""
    @Published var errorBanner: String?
    @Published var draft: String = ""
    @Published private(set) var isSending: Bool = false
    @Published private(set) var pendingToolApprovals: [ToolRunStatus] = []
    @Published private(set) var decidingToolRunIDs: Set<String> = []
    @Published private(set) var unreadMessageCount: Int = 0
    @Published private(set) var isChatWindowVisible: Bool = false
    @Published private(set) var isChatPinned: Bool = false
    @Published private(set) var didInitialStatusCheck: Bool = false
    @Published private(set) var hasWorkingConnection: Bool = false
    @Published private(set) var isTranscribing: Bool = false
    @Published private(set) var isTranscriptionStarting: Bool = false
    @Published private(set) var transcriptionStatusText: String = ""
    @Published private(set) var isConversationWindowVisible: Bool = false
    @Published private(set) var isConversationListening: Bool = false
    @Published private(set) var isConversationStarting: Bool = false
    @Published private(set) var isConversationAwaitingReply: Bool = false
    @Published private(set) var conversationStatusText: String = ""
    @Published private(set) var conversationTranscriptText: String = ""
    @Published private(set) var conversationResponseText: String = ""
    @Published private(set) var conversationModelName: String = ""
    @Published private(set) var isConversationTTSPlaying: Bool = false
    @Published private(set) var conversationTTSLevel: Double = 0
    @Published private(set) var whisperDownloadInProgress: Bool = false
    @Published private(set) var whisperDownloadProgress: Double = 0
    @Published private(set) var whisperDownloadStatusText: String = ""
    @Published private(set) var currentUserID: String = ""
    @Published private(set) var currentUserDisplayName: String = ""

    let settings: SettingsStore
    private let api: APIClient
    private let speechTranscriber = SpeechTranscriber()
    private let conversationTranscriber = SpeechTranscriber()
    private let ttsPlayer = OpenAITTSPlayer()
    private var pollTask: Task<Void, Never>?
    private var requestStartedAt: Date?
    private var lastModelFetchAt: Date?
    private var lastAuthUserFetchAt: Date?
    private var localOverlayMessages: [ChatMessage] = []
    private var draftPrefixBeforeTranscription: String = ""
    private var conversationLatestTranscript: String = ""
    private var conversationSilenceTask: Task<Void, Never>?
    private var conversationSubmitTask: Task<Void, Never>?
    private var conversationTTSTask: Task<Void, Never>?
    private var whisperDownloadRequestID = UUID()

    static let commands: [LocalCommand] = [
        LocalCommand(id: "help", name: "/help", usage: "/help", description: "Show available commands"),
        LocalCommand(id: "new", name: "/new", usage: "/new", description: "Start a new session"),
        LocalCommand(id: "memory_reindex", name: "/memory_reindex", usage: "/memory_reindex", description: "Rebuild memory embeddings"),
        LocalCommand(id: "memory_search", name: "/memory_search", usage: "/memory_search <query>", description: "Search semantic memory"),
        LocalCommand(id: "schedule_list", name: "/schedule_list", usage: "/schedule_list", description: "List scheduled jobs"),
        LocalCommand(id: "schedule_delete", name: "/schedule_delete", usage: "/schedule_delete <job_id>", description: "Delete a scheduled job"),
        LocalCommand(id: "schedule_pause", name: "/schedule_pause", usage: "/schedule_pause <job_id>", description: "Pause a scheduled job"),
        LocalCommand(id: "schedule_resume", name: "/schedule_resume", usage: "/schedule_resume <job_id>", description: "Resume a scheduled job"),
        LocalCommand(id: "tools", name: "/tools", usage: "/tools", description: "Show tool approval settings"),
        LocalCommand(id: "model", name: "/model", usage: "/model [provider/model]", description: "List/set active model"),
        LocalCommand(id: "machine", name: "/machine", usage: "/machine [name_or_id]", description: "List/set default machine"),
        LocalCommand(id: "pair", name: "/pair", usage: "/pair", description: "Create a pair code"),
        LocalCommand(id: "info", name: "/info", usage: "/info", description: "Show session usage info"),
    ]

    init(settings: SettingsStore) {
        self.settings = settings
        self.api = APIClient(settings: settings)
        self.conversationModelName = settings.conversationModelName.trimmingCharacters(in: .whitespacesAndNewlines)
        self.ttsPlayer.onPlaybackStateChange = { [weak self] isPlaying in
            self?.isConversationTTSPlaying = isPlaying
            if !isPlaying {
                self?.conversationTTSLevel = 0
            }
        }
        self.ttsPlayer.onLevelChange = { [weak self] level in
            self?.conversationTTSLevel = max(0, min(1, level))
        }
    }

    deinit {
        pollTask?.cancel()
    }

    func start() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            guard let self else { return }
            await self.pollLoop()
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
        stopTranscription(clearStatus: true)
        stopConversationListening(statusText: "")
    }

    func reconnect() async {
        stopTranscription(clearStatus: true)
        stopConversationListening(statusText: "")
        sessionID = nil
        messages = []
        localOverlayMessages = []
        health = .checking
        activity = .idle
        progressStatusText = ""
        pendingToolApprovals = []
        decidingToolRunIDs = []
        unreadMessageCount = 0
        isChatWindowVisible = false
        await refreshStatus()
    }

    func logout() async {
        stopTranscription(clearStatus: true)
        stopConversationListening(statusText: "")
        settings.apiKey = ""
        currentUserID = ""
        currentUserDisplayName = ""
        lastAuthUserFetchAt = nil
        lastModelFetchAt = nil
        sessionID = nil
        messages = []
        localOverlayMessages = []
        pendingToolApprovals = []
        decidingToolRunIDs = []
        unreadMessageCount = 0
        isSending = false
        requestStartedAt = nil
        progressStatusText = ""
        activity = .idle
        hasWorkingConnection = false
        didInitialStatusCheck = false
        errorBanner = nil
        health = .checking
        await refreshStatus()
    }

    var hasUnreadMessages: Bool {
        unreadMessageCount > 0
    }

    var shouldShowOnboarding: Bool {
        let missingAPIURL = settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let missingAPIKey = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if missingAPIURL || missingAPIKey {
            return true
        }
        return didInitialStatusCheck && !hasWorkingConnection
    }

    func isDecidingToolRun(id: String) -> Bool {
        decidingToolRunIDs.contains(id)
    }

    func approveToolRun(id: String) async {
        await decideToolRun(id: id, approved: true)
    }

    func denyToolRun(id: String) async {
        await decideToolRun(id: id, approved: false)
    }

    func ensureSession(forceNew: Bool = false, syncWithServer: Bool = false) async throws -> String {
        if !forceNew {
            let id = try await api.createOrResumeSession(origin: "menubar", reuseActive: true)
            let previousSessionID = sessionID
            let shouldLoadHistory = id != previousSessionID
            if shouldLoadHistory {
                localOverlayMessages.removeAll()
            }
            sessionID = id
            if shouldLoadHistory || syncWithServer {
                let synced = try await api.sessionDetail(sessionID: id)
                if shouldLoadHistory {
                    messages = synced
                    unreadMessageCount = 0
                } else {
                    applySyncedMessages(synced)
                }
            }
            return id
        }

        let previousSessionID = sessionID
        let id = try await api.createOrResumeSession(origin: "menubar", reuseActive: false)
        let shouldLoadHistory = id != previousSessionID
        if shouldLoadHistory {
            localOverlayMessages.removeAll()
        }
        sessionID = id

        if shouldLoadHistory || syncWithServer {
            let synced = try await api.sessionDetail(sessionID: id)
            if shouldLoadHistory {
                messages = synced
                unreadMessageCount = 0
            } else {
                applySyncedMessages(synced)
            }
        }
        return id
    }

    func filteredCommands(for input: String) -> [LocalCommand] {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard trimmed.hasPrefix("/") else { return [] }
        if trimmed == "/" {
            return Self.commands
        }
        return Self.commands.filter { $0.name.lowercased().hasPrefix(trimmed) || $0.usage.lowercased().hasPrefix(trimmed) }
    }

    func dismissErrorBanner() {
        errorBanner = nil
    }

    func switchModel(to model: String) async {
        do {
            let id = try await ensureSession(forceNew: false)
            let selected = try await api.setSessionModel(sessionID: id, modelName: model)
            modelName = selected
            if !availableModels.contains(selected) {
                availableModels.append(selected)
                availableModels.sort()
            }
            await refreshStatus()
        } catch {
            setError(error)
        }
    }

    func downloadSelectedWhisperModel() async {
        if whisperDownloadInProgress {
            return
        }
        let model = settings.whisperModel.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !model.isEmpty else {
            whisperDownloadStatusText = "Select a Whisper model first."
            return
        }

        let requestID = UUID()
        whisperDownloadRequestID = requestID
        whisperDownloadInProgress = true
        whisperDownloadProgress = 0
        whisperDownloadStatusText = "Downloading \(model)…"
        errorBanner = nil

        do {
            let folderURL = try await WhisperKit.download(
                variant: model,
                progressCallback: { [weak self] progress in
                    Task { @MainActor in
                        guard let self else { return }
                        guard self.whisperDownloadRequestID == requestID else { return }
                        let fraction = min(1.0, max(0.0, progress.fractionCompleted))
                        self.whisperDownloadProgress = fraction.isFinite ? fraction : 0
                        let percent = Int((self.whisperDownloadProgress * 100).rounded())
                        self.whisperDownloadStatusText = "Downloading \(model)… \(percent)%"
                    }
                }
            )
            settings.setWhisperModelFolder(folderURL.path, for: model)
            guard whisperDownloadRequestID == requestID else { return }
            whisperDownloadProgress = 1
            whisperDownloadStatusText = "Model \(model) downloaded."
        } catch {
            guard whisperDownloadRequestID == requestID else { return }
            whisperDownloadStatusText = "Download failed: \(error.localizedDescription)"
            setError(error)
        }
        guard whisperDownloadRequestID == requestID else { return }
        whisperDownloadInProgress = false
    }

    func bootstrapAccount(setupCode: String, displayName: String) async {
        let trimmedCode = setupCode.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedName = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedCode.isEmpty else {
            errorBanner = "Setup code is required."
            return
        }
        guard !trimmedName.isEmpty else {
            errorBanner = "Display name is required."
            return
        }
        do {
            let result = try await api.bootstrap(
                bootstrapCode: trimmedCode,
                displayName: trimmedName,
                deviceName: Host.current().localizedName,
                deviceType: "menubar"
            )
            settings.apiKey = result.token
            currentUserID = result.user.id
            currentUserDisplayName = result.user.displayName
            errorBanner = nil
            await reconnect()
        } catch {
            setError(error)
        }
    }

    func pairAccount(pairCode: String) async {
        let trimmed = pairCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorBanner = "Pair code is required."
            return
        }
        do {
            let result = try await api.pair(
                pairCode: trimmed,
                deviceName: Host.current().localizedName,
                deviceType: "menubar"
            )
            settings.apiKey = result.token
            currentUserID = result.user.id
            currentUserDisplayName = result.user.displayName
            errorBanner = nil
            await reconnect()
        } catch {
            setError(error)
        }
    }

    func testServerConnection() async -> Bool {
        do {
            let ok = try await api.health()
            if ok {
                errorBanner = nil
            } else {
                errorBanner = "Server health check reported a non-OK status."
            }
            return ok
        } catch {
            setError(error)
            return false
        }
    }

    func clearWhisperDownloadStateForModelChange() {
        whisperDownloadRequestID = UUID()
        whisperDownloadInProgress = false
        whisperDownloadProgress = 0
        whisperDownloadStatusText = ""
    }

    func fetchAttachmentData(url: URL) async -> Data? {
        do {
            return try await api.fetchData(from: url.absoluteString)
        } catch {
            setError(error)
            return nil
        }
    }

    func openAttachment(url: URL, preferredName: String) async {
        guard let data = await fetchAttachmentData(url: url) else { return }
        do {
            let tmpDir = FileManager.default.temporaryDirectory
            let fileURL = uniqueURL(baseDir: tmpDir, preferredName: preferredName)
            try data.write(to: fileURL, options: .atomic)
            NSWorkspace.shared.open(fileURL)
        } catch {
            setError(error)
        }
    }

    func downloadAttachment(url: URL, preferredName: String) async {
        guard let data = await fetchAttachmentData(url: url) else { return }
        do {
            let downloadsDir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
                ?? FileManager.default.temporaryDirectory
            let destination = uniqueURL(baseDir: downloadsDir, preferredName: preferredName)
            try data.write(to: destination, options: .atomic)
            NSWorkspace.shared.activateFileViewerSelecting([destination])
        } catch {
            setError(error)
        }
    }

    func sendCurrentDraft() async {
        if isTranscribing {
            stopTranscription(clearStatus: true)
        }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        if await handleLocalCommandIfNeeded(text) {
            return
        }
        await send(text: text)
    }

    private func handleLocalCommandIfNeeded(_ text: String) async -> Bool {
        guard text.hasPrefix("/") else { return false }
        let parts = text.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true)
        guard let rawCommand = parts.first else { return false }
        let command = rawCommand.lowercased()
        let argument = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespacesAndNewlines) : ""
        switch command {
        case "/help":
            appendLocalMessage(
                """
                Available commands:
                \(Self.commands.map { "- \($0.usage): \($0.description)" }.joined(separator: "\n"))
                """
            )
            return true
        case "/new":
            if let result = await runRemoteCommand(name: "new") {
                if let data = result.data,
                   let sessionID = jsonString(data["session_id"]),
                   !sessionID.isEmpty
                {
                    self.sessionID = nil
                    do {
                        _ = try await ensureSession(forceNew: false, syncWithServer: true)
                    } catch {
                        setError(error)
                    }
                }
            }
            return true
        case "/memory_reindex":
            _ = await runRemoteCommand(name: "memory_reindex")
            return true
        case "/memory_search":
            guard !argument.isEmpty else {
                appendLocalMessage("Usage: /memory_search <query>")
                return true
            }
            _ = await runRemoteCommand(name: "memory_search", args: ["query": argument])
            return true
        case "/schedule_list":
            _ = await runRemoteCommand(name: "schedule_list")
            return true
        case "/schedule_delete":
            guard !argument.isEmpty else {
                appendLocalMessage("Usage: /schedule_delete <job_id>")
                return true
            }
            _ = await runRemoteCommand(name: "schedule_delete", args: ["job_id": argument])
            return true
        case "/schedule_pause":
            guard !argument.isEmpty else {
                appendLocalMessage("Usage: /schedule_pause <job_id>")
                return true
            }
            _ = await runRemoteCommand(name: "schedule_pause", args: ["job_id": argument])
            return true
        case "/schedule_resume":
            guard !argument.isEmpty else {
                appendLocalMessage("Usage: /schedule_resume <job_id>")
                return true
            }
            _ = await runRemoteCommand(name: "schedule_resume", args: ["job_id": argument])
            return true
        case "/tools":
            _ = await runRemoteCommand(name: "tools")
            return true
        case "/model":
            let args = argument.isEmpty ? [:] : ["model_name": argument]
            _ = await runRemoteCommand(name: "model", args: args)
            await refreshStatus()
            return true
        case "/machine":
            let args = argument.isEmpty ? [:] : ["target_machine": argument]
            _ = await runRemoteCommand(name: "machine", args: args)
            return true
        case "/pair":
            if !argument.isEmpty && !hasWorkingConnection {
                await pairAccount(pairCode: argument)
                return true
            }
            _ = await runRemoteCommand(name: "pair")
            return true
        case "/info":
            _ = await runRemoteCommand(name: "info")
            return true
        default:
            appendLocalMessage("Unknown command: \(command). Use /help.")
            return true
        }
    }

    private func runRemoteCommand(name: String, args: [String: String] = [:]) async -> CommandResult? {
        do {
            let result = try await api.executeCommand(command: name, args: args, origin: "menubar")
            if !result.message.isEmpty {
                appendLocalMessage(result.message)
            } else {
                appendLocalMessage("Command completed.")
            }
            return result
        } catch {
            setError(error)
            return nil
        }
    }

    private func jsonString(_ value: JSONValue?) -> String? {
        guard let value else { return nil }
        if case let .string(text) = value {
            return text
        }
        return nil
    }

    func setConversationWindowVisible(_ visible: Bool) {
        isConversationWindowVisible = visible
        if visible {
            Task { [weak self] in
                await self?.startConversationListening()
            }
        } else {
            stopConversationListening(statusText: "")
        }
    }

    func toggleConversationListening() async {
        if isConversationListening || isConversationStarting {
            stopConversationListening(statusText: "Paused")
            return
        }
        await startConversationListening()
    }

    private func startConversationListening() async {
        guard isConversationWindowVisible else { return }
        guard !isConversationListening else { return }
        guard !isConversationStarting else { return }

        if isTranscribing {
            stopTranscription(clearStatus: true)
        }

        isConversationStarting = true
        isConversationAwaitingReply = false
        conversationStatusText = "Starting local Whisper…"
        conversationTranscriptText = ""
        conversationLatestTranscript = ""
        conversationSilenceTask?.cancel()
        conversationSilenceTask = nil

        do {
            try await conversationTranscriber.requestMicrophonePermission()
            var folderPath = settings.whisperModelFolder(for: settings.whisperModel)
            if folderPath == nil {
                do {
                    let discovered = try await WhisperKit.download(variant: settings.whisperModel)
                    settings.setWhisperModelFolder(discovered.path, for: settings.whisperModel)
                    folderPath = discovered.path
                } catch {
                    // Keep graceful failure path below; transcriber will report a clear "model not downloaded" message.
                }
            }
            try await conversationTranscriber.startStreaming(
                modelName: settings.whisperModel,
                modelFolderPath: folderPath,
                failOnNoAudio: false,
                onStatus: { [weak self] status in
                    guard let self else { return }
                    guard self.isConversationWindowVisible else { return }
                    self.conversationStatusText = status
                },
                onPartial: { [weak self] partial in
                    guard let self else { return }
                    self.handleConversationPartial(partial)
                },
                onError: { [weak self] error in
                    guard let self else { return }
                    self.stopConversationListening(statusText: "")
                    self.setError(error)
                }
            )
            isConversationListening = true
            isConversationStarting = false
            conversationStatusText = "Listening…"
            errorBanner = nil
        } catch {
            stopConversationListening(statusText: "")
            setError(error)
        }
    }

    private func stopConversationListening(statusText: String) {
        conversationSilenceTask?.cancel()
        conversationSilenceTask = nil
        conversationSubmitTask?.cancel()
        conversationSubmitTask = nil
        stopConversationTTS()
        conversationTranscriber.cancelRecording()
        isConversationListening = false
        isConversationStarting = false
        isConversationAwaitingReply = false
        conversationStatusText = statusText
        conversationTranscriptText = ""
        conversationLatestTranscript = ""
    }

    private func handleConversationPartial(_ partial: String) {
        guard isConversationListening else { return }
        guard !isConversationAwaitingReply else { return }
        let trimmed = cleanedConversationTranscript(from: partial)
        guard !trimmed.isEmpty else { return }
        if trimmed == conversationLatestTranscript {
            return
        }
        if conversationTranscriptText.isEmpty {
            stopConversationTTS()
            conversationResponseText = ""
        }
        conversationLatestTranscript = trimmed
        conversationTranscriptText = trimmed
        scheduleConversationAutoSend(expectedTranscript: trimmed)
    }

    private func cleanedConversationTranscript(from raw: String) -> String {
        var cleaned = raw
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            return ""
        }

        if (cleaned.hasPrefix("[") && cleaned.hasSuffix("]"))
            || (cleaned.hasPrefix("(") && cleaned.hasSuffix(")")) {
            return ""
        }

        cleaned = cleaned.replacingOccurrences(of: #"\s{2,}"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if cleaned.isEmpty {
            return ""
        }

        let alnumCount = cleaned.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.count
        if alnumCount < 2 {
            return ""
        }

        return cleaned
    }

    private func scheduleConversationAutoSend(expectedTranscript: String) {
        conversationSilenceTask?.cancel()
        let silenceSeconds = max(0.4, settings.conversationSilenceSeconds)
        let delayNanos = UInt64((silenceSeconds * 1_000_000_000).rounded())
        conversationSilenceTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delayNanos)
            guard !Task.isCancelled else { return }
            await self?.enqueueConversationSubmit(expectedTranscript: expectedTranscript)
        }
    }

    private func enqueueConversationSubmit(expectedTranscript: String) async {
        conversationSilenceTask = nil
        guard conversationSubmitTask == nil else { return }
        conversationSubmitTask = Task { [weak self] in
            guard let self else { return }
            await self.submitConversationTranscriptIfReady(expectedTranscript: expectedTranscript)
            self.conversationSubmitTask = nil
        }
    }

    private func submitConversationTranscriptIfReady(expectedTranscript: String) async {
        guard isConversationListening else { return }
        guard !isConversationAwaitingReply else {
            scheduleConversationAutoSend(expectedTranscript: expectedTranscript)
            return
        }
        guard !isSending else {
            scheduleConversationAutoSend(expectedTranscript: expectedTranscript)
            return
        }
        let text = conversationLatestTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard text == expectedTranscript else { return }
        let silenceSeconds = max(0.4, settings.conversationSilenceSeconds)
        if conversationTranscriber.hasRecentSpeechActivity(within: silenceSeconds) {
            scheduleConversationAutoSend(expectedTranscript: expectedTranscript)
            return
        }

        let previousAssistantID = messages.reversed().first(where: { $0.role == .assistant })?.id

        conversationSilenceTask?.cancel()
        conversationSilenceTask = nil
        conversationLatestTranscript = ""
        conversationTranscriptText = ""
        conversationResponseText = ""
        stopConversationTTS()
        isConversationAwaitingReply = true
        conversationStatusText = "Sending…"
        conversationTranscriber.resetStreamingBuffer()

        let sendResult = await sendConversationUtterance(text: text, previousAssistantID: previousAssistantID)
        if let immediateReply = sendResult.immediateReply {
            applyConversationAssistantReply(immediateReply)
            isConversationAwaitingReply = false
            conversationStatusText = isConversationListening ? "Listening…" : ""
            return
        }

        if sendResult.shouldPollForReply, let activeSessionID = sendResult.sessionID ?? sessionID {
            conversationStatusText = "Waiting for response…"
            if let reply = await waitForConversationAssistantReply(
                sessionID: activeSessionID,
                previousAssistantID: previousAssistantID
            ) {
                applyConversationAssistantReply(reply)
            }
        }
        isConversationAwaitingReply = false
        if !isConversationWindowVisible {
            conversationStatusText = ""
            return
        }
        conversationStatusText = isConversationListening ? "Listening…" : ""
    }

    private func applyConversationAssistantReply(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        conversationResponseText = trimmed
        guard !trimmed.isEmpty else { return }
        playConversationTTSIfConfigured(text: trimmed)
    }

    private func playConversationTTSIfConfigured(text: String) {
        guard isConversationWindowVisible else { return }
        let trimmedKey = settings.openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedKey.isEmpty else { return }

        let baseURL = settings.openAIBaseURL
        let model = settings.openAITTSModel
        let voice = settings.openAITTSVoice

        conversationTTSTask?.cancel()
        conversationTTSTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await self.ttsPlayer.speak(
                    baseURL: baseURL,
                    apiKey: trimmedKey,
                    model: model,
                    voice: voice,
                    text: text
                )
            } catch is CancellationError {
                return
            } catch {
                self.errorBanner = "OpenAI TTS failed: \(error.localizedDescription)"
            }
        }
    }

    private func stopConversationTTS() {
        conversationTTSTask?.cancel()
        conversationTTSTask = nil
        ttsPlayer.stop()
        isConversationTTSPlaying = false
        conversationTTSLevel = 0
    }

    private struct ConversationSendResult {
        let sessionID: String?
        let immediateReply: String?
        let shouldPollForReply: Bool
    }

    private struct ConversationHTTPMessage: Sendable {
        let id: String
        let content: String
        let createdAt: Date
    }

    private struct ConversationReplyProbe: Sendable {
        let id: String
        let content: String
    }

    private enum ConversationNetworkError: LocalizedError {
        case invalidBaseURL
        case missingAuthToken
        case invalidResponse
        case http(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .invalidBaseURL:
                return "Invalid API URL"
            case .missingAuthToken:
                return "Access token is required"
            case .invalidResponse:
                return "Invalid server response"
            case let .http(code, message):
                return "HTTP \(code): \(message)"
            case let .decoding(message):
                return "Decoding error: \(message)"
            }
        }
    }

    private struct ConversationMessageCreateBody: Encodable {
        let session_id: String
        let text: String
        let metadata: [String: String]
    }

    private struct ConversationMessagePayload: Decodable {
        let id: String
        let content: String
        let created_at: String
    }

    nonisolated private static let conversationURLSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 900
        configuration.timeoutIntervalForResource = 3600
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }()

    private func sendConversationUtterance(text: String, previousAssistantID: String?) async -> ConversationSendResult {
        var resolvedSessionID: String?
        do {
            let id = try await ensureSession(forceNew: false)
            resolvedSessionID = id
            let baseURL = settings.apiURL
            let apiKey = settings.apiKey
            let modelNameOverride = conversationModelName.trimmingCharacters(in: .whitespacesAndNewlines)
            let userMessage = ChatMessage(
                id: UUID().uuidString,
                role: .user,
                content: text,
                createdAt: Date(),
                attachments: []
            )
            messages.append(userMessage)
            isSending = true
            requestStartedAt = Date()
            progressStatusText = "Working... 0s\nLast step: thinking"
            activity = .thinking
            errorBanner = nil

            let immediateAssistant = try await Self.performConversationSendRequest(
                baseURL: baseURL,
                apiKey: apiKey,
                sessionID: id,
                text: text,
                modelNameOverride: modelNameOverride.isEmpty ? nil : modelNameOverride
            )
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            activity = .idle

            let immediateAssistantMessage = ChatMessage(
                id: immediateAssistant.id,
                role: .assistant,
                content: immediateAssistant.content,
                createdAt: immediateAssistant.createdAt,
                attachments: []
            )
            if !messages.contains(where: { $0.id == immediateAssistantMessage.id }) {
                messages.append(immediateAssistantMessage)
            }
            let immediateText = immediateAssistantMessage.content.trimmingCharacters(in: .whitespacesAndNewlines)
            if immediateAssistantMessage.id != previousAssistantID && !immediateText.isEmpty {
                return ConversationSendResult(sessionID: id, immediateReply: immediateText, shouldPollForReply: false)
            }
            return ConversationSendResult(sessionID: id, immediateReply: nil, shouldPollForReply: true)
        } catch {
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            activity = .idle

            if isTimeoutError(error), let sessionID = resolvedSessionID {
                return ConversationSendResult(sessionID: sessionID, immediateReply: nil, shouldPollForReply: true)
            }

            setError(error)
            return ConversationSendResult(sessionID: resolvedSessionID, immediateReply: nil, shouldPollForReply: false)
        }
    }

    private func waitForConversationAssistantReply(sessionID: String, previousAssistantID: String?) async -> String? {
        let baseURL = settings.apiURL
        let apiKey = settings.apiKey
        let deadline = Date().addingTimeInterval(180)
        var lastPollError: Error?
        while Date() < deadline {
            do {
                if let latestAssistant = try await Self.fetchLatestAssistantReply(
                    baseURL: baseURL,
                    apiKey: apiKey,
                    sessionID: sessionID,
                    previousAssistantID: previousAssistantID
                )
                {
                    if !messages.contains(where: { $0.id == latestAssistant.id }) {
                        messages.append(
                            ChatMessage(
                                id: latestAssistant.id,
                                role: .assistant,
                                content: latestAssistant.content,
                                createdAt: Date(),
                                attachments: []
                            )
                        )
                    }
                    return latestAssistant.content
                }
            } catch {
                lastPollError = error
            }
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
        if let lastPollError {
            setError(lastPollError)
        }
        return nil
    }

    nonisolated private static func performConversationSendRequest(
        baseURL: String,
        apiKey: String,
        sessionID: String,
        text: String,
        modelNameOverride: String?
    ) async throws -> ConversationHTTPMessage {
        let url = try conversationURL(baseURL: baseURL, pathSegments: ["v1", "messages"])
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else {
            throw ConversationNetworkError.missingAuthToken
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 900
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var metadata: [String: String] = [:]
        if let modelNameOverride {
            let cleaned = modelNameOverride.trimmingCharacters(in: .whitespacesAndNewlines)
            if !cleaned.isEmpty {
                metadata["model_name"] = cleaned
            }
        }
        request.httpBody = try JSONEncoder().encode(
            ConversationMessageCreateBody(session_id: sessionID, text: text, metadata: metadata)
        )

        let (data, response) = try await conversationURLSession.data(for: request)
        try ensureConversationHTTP200(response: response, data: data)

        let payload: ConversationMessagePayload
        do {
            payload = try JSONDecoder().decode(ConversationMessagePayload.self, from: data)
        } catch {
            throw ConversationNetworkError.decoding(error.localizedDescription)
        }

        return ConversationHTTPMessage(
            id: payload.id,
            content: payload.content,
            createdAt: parseConversationDate(payload.created_at)
        )
    }

    nonisolated private static func fetchLatestAssistantReply(
        baseURL: String,
        apiKey: String,
        sessionID: String,
        previousAssistantID: String?
    ) async throws -> ConversationReplyProbe? {
        let url = try conversationURL(baseURL: baseURL, pathSegments: ["v1", "sessions", sessionID, "detail"])
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else {
            throw ConversationNetworkError.missingAuthToken
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 120
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await conversationURLSession.data(for: request)
        try ensureConversationHTTP200(response: response, data: data)

        let root: Any
        do {
            root = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw ConversationNetworkError.decoding(error.localizedDescription)
        }
        guard let object = root as? [String: Any],
              let messages = object["messages"] as? [[String: Any]]
        else {
            throw ConversationNetworkError.decoding("Missing messages field")
        }

        for message in messages.reversed() {
            guard let role = message["role"] as? String, role.lowercased() == "assistant" else {
                continue
            }
            guard let id = message["id"] as? String else {
                continue
            }
            if let previousAssistantID, id == previousAssistantID {
                continue
            }
            let content = (message["content"] as? String) ?? ""
            return ConversationReplyProbe(id: id, content: content)
        }
        return nil
    }

    nonisolated private static func conversationURL(baseURL: String, pathSegments: [String]) throws -> URL {
        let trimmedBase = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmedBase) else {
            throw ConversationNetworkError.invalidBaseURL
        }
        if components.host?.lowercased() == "localhost" {
            components.host = "127.0.0.1"
        }
        guard let normalizedBase = components.url else {
            throw ConversationNetworkError.invalidBaseURL
        }
        return pathSegments.reduce(normalizedBase) { partial, segment in
            partial.appendingPathComponent(segment)
        }
    }

    nonisolated private static func ensureConversationHTTP200(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw ConversationNetworkError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "request failed"
            throw ConversationNetworkError.http(http.statusCode, message)
        }
    }

    nonisolated private static func parseConversationDate(_ raw: String) -> Date {
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFractional.date(from: raw) {
            return date
        }
        let standard = ISO8601DateFormatter()
        standard.formatOptions = [.withInternetDateTime]
        if let date = standard.date(from: raw) {
            return date
        }
        return Date()
    }

    func toggleTranscription() async {
        if isConversationWindowVisible {
            stopConversationListening(statusText: "Paused")
        }
        if isTranscriptionStarting {
            return
        }
        if isTranscribing {
            await stopStreamingTranscription()
            return
        }
        await startTranscription()
    }

    private func startTranscription() async {
        guard !isTranscriptionStarting else { return }
        isTranscriptionStarting = true
        do {
            try await speechTranscriber.requestMicrophonePermission()
            draftPrefixBeforeTranscription = draft
            transcriptionStatusText = "Starting local Whisper…"
            var folderPath = settings.whisperModelFolder(for: settings.whisperModel)
            if folderPath == nil {
                do {
                    let discovered = try await WhisperKit.download(variant: settings.whisperModel)
                    settings.setWhisperModelFolder(discovered.path, for: settings.whisperModel)
                    folderPath = discovered.path
                } catch {
                    // Keep graceful failure path below; transcriber will report a clear "model not downloaded" message.
                }
            }
            try await speechTranscriber.startStreaming(
                modelName: settings.whisperModel,
                modelFolderPath: folderPath,
                onStatus: { [weak self] status in
                    self?.transcriptionStatusText = status
                },
                onPartial: { [weak self] partial in
                    guard let self else { return }
                    guard self.isTranscribing else { return }
                    let trimmed = partial.trimmingCharacters(in: .whitespacesAndNewlines)
                    if trimmed.isEmpty {
                        self.draft = self.draftPrefixBeforeTranscription
                        return
                    }
                    let needsSpace =
                        !self.draftPrefixBeforeTranscription.isEmpty &&
                        !self.draftPrefixBeforeTranscription.hasSuffix(" ") &&
                        !self.draftPrefixBeforeTranscription.hasSuffix("\n")
                    let separator = needsSpace ? " " : ""
                    self.draft = self.draftPrefixBeforeTranscription + separator + trimmed
                },
                onError: { [weak self] error in
                    guard let self else { return }
                    self.stopTranscription(clearStatus: true)
                    self.setError(error)
                }
            )
            isTranscribing = true
            isTranscriptionStarting = false
            errorBanner = nil
        } catch {
            stopTranscription(clearStatus: true)
            setError(error)
        }
    }

    private func stopStreamingTranscription() async {
        guard isTranscribing else { return }
        do {
            _ = try await speechTranscriber.stopStreaming()
        } catch {
            // Stopping can race with stream teardown; ignore stop-time errors in UI.
        }
        isTranscribing = false
        transcriptionStatusText = ""
        draftPrefixBeforeTranscription = ""
    }

    private func stopTranscription(clearStatus: Bool) {
        speechTranscriber.cancelRecording()
        isTranscribing = false
        isTranscriptionStarting = false
        draftPrefixBeforeTranscription = ""
        if clearStatus {
            transcriptionStatusText = ""
        }
    }

    func send(text: String) async {
        var sessionForRecovery: String?
        var sentAt = Date()
        do {
            let id = try await ensureSession(forceNew: false)
            sessionForRecovery = id
            let userMessage = ChatMessage(
                id: UUID().uuidString,
                role: .user,
                content: text,
                createdAt: Date(),
                attachments: []
            )
            sentAt = userMessage.createdAt
            messages.append(userMessage)
            isSending = true
            requestStartedAt = Date()
            progressStatusText = "Working... 0s\nLast step: thinking"
            activity = .thinking
            errorBanner = nil
            _ = try await api.sendMessage(sessionID: id, text: text)
            let syncedMessages = try await api.sessionDetail(sessionID: id)
            applySyncedMessages(syncedMessages)
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            await refreshStatus()
        } catch {
            if isTimeoutError(error), let sessionID = sessionForRecovery {
                await recoverTimedOutSend(sessionID: sessionID, sentAt: sentAt, timeoutError: error)
                return
            }
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            setError(error)
            activity = .idle
        }
    }

    func markChatOpened() {
        unreadMessageCount = 0
        chatOpenSignal += 1
    }

    func setChatWindowVisible(_ visible: Bool) {
        isChatWindowVisible = visible
        if visible {
            unreadMessageCount = 0
        } else if isTranscribing {
            stopTranscription(clearStatus: true)
        }
    }

    func setChatPinned(_ pinned: Bool) {
        isChatPinned = pinned
    }

    func toggleChatPinned() {
        isChatPinned.toggle()
    }

    func setConversationModelName(_ modelName: String) {
        let cleaned = modelName.trimmingCharacters(in: .whitespacesAndNewlines)
        conversationModelName = cleaned
        settings.conversationModelName = cleaned
        if !cleaned.isEmpty && !availableModels.contains(cleaned) {
            availableModels.append(cleaned)
            availableModels.sort()
        }
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            if isConversationWindowVisible && (isConversationAwaitingReply || isSending) {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                continue
            }
            await refreshStatus()
            let delay = isSending ? 1_000_000_000 : 8_000_000_000
            try? await Task.sleep(nanoseconds: UInt64(delay))
        }
    }

    func refreshStatus() async {
        let refreshStartedAt = DispatchTime.now().uptimeNanoseconds
        var lastError: Error?
        var anySuccess = false
        var sessionCheckSucceeded = false
        var sessionError: Error?

        do {
            let ok = try await api.health()
            anySuccess = true
            if ok {
                health = .healthy
            } else {
                health = .error("health check failed")
            }
        } catch {
            lastError = error
            sessionError = error
        }

        var activeSessionID: String?
        do {
            let shouldSyncMessages = !isChatWindowVisible && !isSending
            let id = try await ensureSession(forceNew: false, syncWithServer: shouldSyncMessages)
            activeSessionID = id
            let snapshot = try await api.sessionSnapshot(sessionID: id)
            contextTokens = snapshot.contextTokens
            totalTokens = snapshot.totalTokens
            sessionCost = snapshot.totalCost
            modelName = snapshot.modelName
            let target = max(1, settings.contextTokenTarget)
            contextProgress = min(1.0, Double(contextTokens) / Double(target))
            anySuccess = true
            if case .checking = health {
                health = .healthy
            }
            if case .error = health {
                health = .healthy
            }
            sessionCheckSucceeded = true
        } catch {
            lastError = error
        }

        if let activeSessionID {
            do {
                pendingToolApprovals = try await api.pendingToolRuns(sessionID: activeSessionID)
                anySuccess = true
            } catch {
                lastError = error
                pendingToolApprovals = []
            }
        } else {
            pendingToolApprovals = []
        }

        let pendingCount = pendingToolApprovals.count
        if isSending {
            activity = .thinking
        } else if pendingCount > 0 {
            activity = .activeTasks(pendingCount)
        } else {
            activity = .idle
        }

        if isSending, let sessionID = activeSessionID {
            let elapsed = max(0, Int(Date().timeIntervalSince(requestStartedAt ?? Date())))
            do {
                if let latest = try await api.latestToolRun(sessionID: sessionID, since: requestStartedAt) {
                    progressStatusText = "Working... \(elapsed)s\nLast tool: `\(latest.tool)` (\(latest.status))"
                } else {
                    progressStatusText = "Working... \(elapsed)s\nLast step: thinking"
                }
            } catch {
                progressStatusText = "Working... \(elapsed)s\nLast step: thinking"
            }
        } else {
            progressStatusText = ""
        }

        if !sessionCheckSucceeded {
            setError(sessionError ?? lastError)
        } else if !anySuccess {
            health = .error(lastError?.localizedDescription ?? "status check failed")
            setError(lastError)
        } else if case .healthy = health {
            errorBanner = nil
        }

        if shouldRefreshModels() {
            do {
                let models = try await api.listModelNames()
                availableModels = models.sorted()
                lastModelFetchAt = Date()
            } catch {
                lastError = error
            }
        }
        if !modelName.isEmpty && !availableModels.contains(modelName) {
            availableModels.append(modelName)
            availableModels.sort()
        }
        if !conversationModelName.isEmpty && !availableModels.contains(conversationModelName) {
            availableModels.append(conversationModelName)
            availableModels.sort()
        }
        if shouldRefreshAuthUser() {
            do {
                let me = try await api.authMe()
                currentUserID = me.id
                currentUserDisplayName = me.displayName
                lastAuthUserFetchAt = Date()
            } catch {
                // ignore: status checks already surface connectivity/auth errors
            }
        }
        hasWorkingConnection = sessionCheckSucceeded
        didInitialStatusCheck = true
        logSlowRefreshStatus(startedAt: refreshStartedAt)
    }

    private func appendLocalMessage(_ content: String) {
        let message = ChatMessage(
            id: UUID().uuidString,
            role: .assistant,
            content: content,
            createdAt: Date(),
            attachments: []
        )
        localOverlayMessages.append(message)
        if localOverlayMessages.count > 200 {
            localOverlayMessages.removeFirst(localOverlayMessages.count - 200)
        }
        messages.append(message)
    }

    private func applySyncedMessages(_ synced: [ChatMessage]) {
        let startedAt = DispatchTime.now().uptimeNanoseconds
        let merged = mergedMessagesWithOverlay(synced)
        if hasSameMessageIdentity(messages, merged) {
            logSlowApplySyncedMessages(startedAt: startedAt, syncedCount: synced.count, mergedCount: merged.count)
            return
        }
        if !isChatWindowVisible {
            let previousAssistantIDs = Set(messages.filter { $0.role == .assistant }.map(\.id))
            let newAssistantCount = synced
                .filter { $0.role == .assistant && !previousAssistantIDs.contains($0.id) }
                .count
            if newAssistantCount > 0 {
                unreadMessageCount += newAssistantCount
            }
        }
        messages = merged
        logSlowApplySyncedMessages(startedAt: startedAt, syncedCount: synced.count, mergedCount: merged.count)
    }

    private func hasSameMessageIdentity(_ lhs: [ChatMessage], _ rhs: [ChatMessage]) -> Bool {
        guard lhs.count == rhs.count else {
            return false
        }
        for (left, right) in zip(lhs, rhs) {
            if left.id != right.id {
                return false
            }
        }
        return true
    }

    private func logSlowApplySyncedMessages(startedAt: UInt64, syncedCount: Int, mergedCount: Int) {
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - startedAt) / 1_000_000
        guard elapsedMs >= 20 else { return }
        let elapsedText = String(format: "%.1f", elapsedMs)
        Self.perfLogger.notice(
            "applySyncedMessages slow: \(elapsedText, privacy: .public)ms synced=\(syncedCount) merged=\(mergedCount)"
        )
    }

    private func logSlowRefreshStatus(startedAt: UInt64) {
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - startedAt) / 1_000_000
        guard elapsedMs >= 120 else { return }
        let elapsedText = String(format: "%.1f", elapsedMs)
        Self.perfLogger.notice("refreshStatus slow: \(elapsedText, privacy: .public)ms")
    }

    private func mergedMessagesWithOverlay(_ synced: [ChatMessage]) -> [ChatMessage] {
        guard !localOverlayMessages.isEmpty else {
            return synced
        }
        let existingIDs = Set(synced.map(\.id))
        var merged = synced
        for message in localOverlayMessages where !existingIDs.contains(message.id) {
            merged.append(message)
        }
        merged.sort { lhs, rhs in
            if lhs.createdAt != rhs.createdAt {
                return lhs.createdAt < rhs.createdAt
            }
            return lhs.id < rhs.id
        }
        return merged
    }

    private func setError(_ error: Error?) {
        let text = (error?.localizedDescription ?? "Unknown error")
        let lower = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if lower == "cancelled" || lower == "canceled" {
            return
        }
        health = .error(text)
        if lower.contains("not yet approved") || lower.contains("admin has to approve it first") {
            errorBanner = "Your account is not yet approved. An admin has to approve it first."
            return
        }
        if lower.contains("whisper model") && lower.contains("not downloaded") {
            errorBanner = text
            return
        }
        if text.contains("HTTP 401") || lower.contains("invalid authentication token") || text.localizedCaseInsensitiveContains("Invalid API key") {
            errorBanner = "Invalid access token. Use setup/pair flow in onboarding or Settings."
            return
        }
        if text.contains("HTTP 503") {
            errorBanner = "Server unavailable. Check API URL and server status."
            return
        }
        errorBanner = text
    }

    private func shouldRefreshModels() -> Bool {
        if availableModels.isEmpty || lastModelFetchAt == nil {
            return true
        }
        guard let last = lastModelFetchAt else { return true }
        return Date().timeIntervalSince(last) >= 60
    }

    private func shouldRefreshAuthUser() -> Bool {
        if settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return false
        }
        if currentUserID.isEmpty || lastAuthUserFetchAt == nil {
            return true
        }
        guard let last = lastAuthUserFetchAt else { return true }
        return Date().timeIntervalSince(last) >= 120
    }

    private func decideToolRun(id: String, approved: Bool) async {
        guard !decidingToolRunIDs.contains(id) else { return }
        decidingToolRunIDs.insert(id)
        defer {
            decidingToolRunIDs.remove(id)
        }
        let decidedBy = decisionActor()
        do {
            if approved {
                try await api.approveToolRun(toolRunID: id, decidedBy: decidedBy)
            } else {
                try await api.denyToolRun(toolRunID: id, decidedBy: decidedBy)
            }
            pendingToolApprovals.removeAll { $0.id == id }
            await refreshStatus()
        } catch {
            setError(error)
        }
    }

    private func decisionActor() -> String {
        if !currentUserID.isEmpty {
            return currentUserID
        }
        return "menubar"
    }

    private func isTimeoutError(_ error: Error) -> Bool {
        if let urlError = error as? URLError {
            return urlError.code == .timedOut
        }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == URLError.timedOut.rawValue {
            return true
        }
        return nsError.localizedDescription.localizedCaseInsensitiveContains("timed out")
    }

    private func recoverTimedOutSend(sessionID: String, sentAt: Date, timeoutError: Error) async {
        errorBanner = "The request timed out locally. Waiting for server result..."
        let deadline = Date().addingTimeInterval(180)
        while Date() < deadline {
            do {
                let syncedMessages = try await api.sessionDetail(sessionID: sessionID)
                if !syncedMessages.isEmpty {
                    if !isChatWindowVisible {
                        let knownAssistantIDs = Set(messages.filter { $0.role == .assistant }.map(\.id))
                        let newAssistantMessages = syncedMessages.filter { $0.role == .assistant && !knownAssistantIDs.contains($0.id) }
                        unreadMessageCount += newAssistantMessages.count
                    }
                    applySyncedMessages(syncedMessages)
                }
                let hasAssistantReply = syncedMessages.contains { message in
                    message.role == .assistant && message.createdAt >= sentAt
                }
                if hasAssistantReply {
                    isSending = false
                    requestStartedAt = nil
                    progressStatusText = ""
                    errorBanner = nil
                    await refreshStatus()
                    return
                }
            } catch {
                // Keep polling while the backend run is still in progress.
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
        isSending = false
        requestStartedAt = nil
        progressStatusText = ""
        setError(timeoutError)
        activity = .idle
    }

    private func uniqueURL(baseDir: URL, preferredName: String) -> URL {
        let cleanName = preferredName.trimmingCharacters(in: .whitespacesAndNewlines)
        let raw = cleanName.isEmpty ? "attachment" : cleanName
        let safe = raw.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
        var url = baseDir.appendingPathComponent(safe)
        if !FileManager.default.fileExists(atPath: url.path) {
            return url
        }
        let ext = url.pathExtension
        let stem = url.deletingPathExtension().lastPathComponent
        let stamp = Int(Date().timeIntervalSince1970)
        if ext.isEmpty {
            url = baseDir.appendingPathComponent("\(stem)-\(stamp)")
        } else {
            url = baseDir.appendingPathComponent("\(stem)-\(stamp)").appendingPathExtension(ext)
        }
        return url
    }
}
