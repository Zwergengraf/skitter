import Foundation
import AppKit

struct LocalCommand: Identifiable {
    let id: String
    let name: String
    let usage: String
    let description: String
}

@MainActor
final class AppState: ObservableObject {
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
    @Published private(set) var didInitialStatusCheck: Bool = false
    @Published private(set) var hasWorkingConnection: Bool = false

    let settings: SettingsStore
    private let api: APIClient
    private var pollTask: Task<Void, Never>?
    private var requestStartedAt: Date?
    private var lastModelFetchAt: Date?

    static let commands: [LocalCommand] = [
        LocalCommand(id: "help", name: "/help", usage: "/help", description: "Show available commands"),
        LocalCommand(id: "new", name: "/new", usage: "/new", description: "Start a new menubar session"),
        LocalCommand(id: "status", name: "/status", usage: "/status", description: "Show current connection/session status"),
        LocalCommand(id: "reconnect", name: "/reconnect", usage: "/reconnect", description: "Reconnect and reload session"),
        LocalCommand(id: "memory", name: "/memory", usage: "/memory", description: "Show memory guidance"),
    ]

    init(settings: SettingsStore) {
        self.settings = settings
        self.api = APIClient(settings: settings)
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
    }

    func reconnect() async {
        sessionID = nil
        messages = []
        health = .checking
        activity = .idle
        progressStatusText = ""
        pendingToolApprovals = []
        decidingToolRunIDs = []
        unreadMessageCount = 0
        isChatWindowVisible = false
        await refreshStatus()
    }

    var hasUnreadMessages: Bool {
        unreadMessageCount > 0
    }

    var shouldShowOnboarding: Bool {
        let missingAPIURL = settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let missingAPIKey = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let missingUserID = settings.userID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if missingAPIURL || missingAPIKey || missingUserID {
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
        if let sessionID, !forceNew, !syncWithServer {
            return sessionID
        }
        let id = try await api.createOrResumeSession(origin: "menubar", reuseActive: !forceNew)
        let shouldLoadHistory = id != sessionID
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
            do {
                _ = try await ensureSession(forceNew: true)
                appendLocalMessage("Started a new menubar session.")
            } catch {
                setError(error)
            }
            return true
        case "/status":
            let session = sessionID ?? "(none)"
            appendLocalMessage(
                """
                Status: \(health.label), \(activity.label)
                Session: \(session)
                Model: \(modelName)
                Tokens: \(totalTokens)
                Cost: $\(String(format: "%.4f", sessionCost))
                """
            )
            return true
        case "/reconnect":
            await reconnect()
            appendLocalMessage("Reconnected.")
            return true
        case "/memory":
            appendLocalMessage("Memory operations are available in the admin web UI.")
            return true
        default:
            appendLocalMessage("Unknown command: \(command). Use /help.")
            return true
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
        }
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await refreshStatus()
            let delay = isSending ? 1_000_000_000 : 5_000_000_000
            try? await Task.sleep(nanoseconds: UInt64(delay))
        }
    }

    func refreshStatus() async {
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
            let id = try await ensureSession(forceNew: false, syncWithServer: !isSending)
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

        var pendingCount = 0
        do {
            pendingCount = try await api.pendingToolCount()
            anySuccess = true
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
        hasWorkingConnection = sessionCheckSucceeded
        didInitialStatusCheck = true
    }

    private func appendLocalMessage(_ content: String) {
        let message = ChatMessage(
            id: UUID().uuidString,
            role: .assistant,
            content: content,
            createdAt: Date(),
            attachments: []
        )
        messages.append(message)
    }

    private func applySyncedMessages(_ synced: [ChatMessage]) {
        if messages == synced {
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
        messages = synced
    }

    private func setError(_ error: Error?) {
        let text = (error?.localizedDescription ?? "Unknown error")
        health = .error(text)
        let lower = text.lowercased()
        if lower.contains("not yet approved") || lower.contains("admin has to approve it first") {
            errorBanner = "Your account is not yet approved. An admin has to approve it first."
            return
        }
        if text.contains("HTTP 401") || text.localizedCaseInsensitiveContains("Invalid API key") {
            errorBanner = "Invalid API key. Update Settings and reconnect."
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
        let userID = settings.userID.trimmingCharacters(in: .whitespacesAndNewlines)
        return userID.isEmpty ? "menubar" : userID
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
                    messages = syncedMessages
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
