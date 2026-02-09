import Foundation

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
    @Published private(set) var sessionID: String?
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var chatOpenSignal: Int = 0
    @Published private(set) var progressStatusText: String = ""
    @Published var errorBanner: String?
    @Published var draft: String = ""
    @Published private(set) var isSending: Bool = false

    let settings: SettingsStore
    private let api: APIClient
    private var pollTask: Task<Void, Never>?
    private var requestStartedAt: Date?

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
        await refreshStatus()
    }

    func ensureSession(forceNew: Bool = false) async throws -> String {
        if let sessionID, !forceNew {
            return sessionID
        }
        let id = try await api.createOrResumeSession(origin: "menubar", reuseActive: !forceNew)
        let shouldLoadHistory = id != sessionID
        sessionID = id
        if shouldLoadHistory {
            messages = try await api.sessionDetail(sessionID: id)
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
        do {
            let id = try await ensureSession(forceNew: false)
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
            let assistantMessage = try await api.sendMessage(sessionID: id, text: text)
            messages.append(assistantMessage)
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            await refreshStatus()
        } catch {
            isSending = false
            requestStartedAt = nil
            progressStatusText = ""
            setError(error)
            activity = .idle
        }
    }

    func markChatOpened() {
        chatOpenSignal += 1
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
        }

        var activeSessionID: String?
        do {
            let id = try await ensureSession(forceNew: false)
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
                if let latest = try await api.latestToolRun(sessionID: sessionID) {
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

        if !anySuccess {
            health = .error(lastError?.localizedDescription ?? "status check failed")
            setError(lastError)
        }
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

    private func setError(_ error: Error?) {
        let text = (error?.localizedDescription ?? "Unknown error")
        health = .error(text)
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
}
