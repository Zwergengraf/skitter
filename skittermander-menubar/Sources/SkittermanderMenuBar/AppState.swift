import Foundation

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var health: HealthState = .checking
    @Published private(set) var activity: ActivityState = .idle
    @Published private(set) var contextTokens: Int = 0
    @Published private(set) var contextProgress: Double = 0
    @Published private(set) var sessionCost: Double = 0
    @Published private(set) var sessionID: String?
    @Published private(set) var messages: [ChatMessage] = []
    @Published var draft: String = ""
    @Published private(set) var isSending: Bool = false

    let settings: SettingsStore
    private let api: APIClient
    private var pollTask: Task<Void, Never>?

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

    func sendCurrentDraft() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        await send(text: text)
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
            activity = .thinking
            let assistantMessage = try await api.sendMessage(sessionID: id, text: text)
            messages.append(assistantMessage)
            isSending = false
            await refreshStatus()
        } catch {
            isSending = false
            health = .error(error.localizedDescription)
            activity = .idle
        }
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await refreshStatus()
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }

    func refreshStatus() async {
        do {
            let ok = try await api.health()
            health = ok ? .healthy : .error("health check failed")
            let id = try await ensureSession(forceNew: false)
            let snapshot = try await api.sessionSnapshot(sessionID: id)
            contextTokens = snapshot.contextTokens
            sessionCost = snapshot.totalCost
            let target = max(1, settings.contextTokenTarget)
            contextProgress = min(1.0, Double(contextTokens) / Double(target))
            let pending = try await api.pendingToolCount()
            if isSending {
                activity = .thinking
            } else if pending > 0 {
                activity = .activeTasks(pending)
            } else {
                activity = .idle
            }
        } catch {
            health = .error(error.localizedDescription)
            if !isSending {
                activity = .idle
            }
        }
    }
}
