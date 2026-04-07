import Foundation
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var authenticationState: AuthenticationState = .loading
    @Published private(set) var health: HealthState = .checking
    @Published private(set) var activity: ActivityState = .idle
    @Published private(set) var currentUser: AuthUser?
    @Published private(set) var profiles: [AgentProfile] = []
    @Published private(set) var sessionID: String?
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var pendingComposerAttachments: [PendingComposerAttachment] = []
    @Published private(set) var pendingApprovals: [ToolRunStatus] = []
    @Published private(set) var pendingPrompts: [PendingUserPrompt] = []
    @Published private(set) var availableModels: [String] = []
    @Published private(set) var modelName: String = "default"
    @Published private(set) var contextTokens: Int = 0
    @Published private(set) var totalTokens: Int = 0
    @Published private(set) var sessionCost: Double = 0
    @Published private(set) var unreadCount: Int = 0
    @Published private(set) var isSending: Bool = false
    @Published private(set) var isRefreshing: Bool = false
    @Published var errorText: String?
    @Published var draft: String = ""
    @Published var selectedSection: AppSection = .chat

    let settings: SettingsStore

    private let apiClient: APIClient
    private let notificationManager: NotificationManager
    private var pollTask: Task<Void, Never>?
    private var hasStarted = false
    private var didPrimeMessageBaseline = false
    private var lastModelRefreshAt: Date?
    private var isSceneActive = true
    private var isChatVisible = true

    init(settings: SettingsStore, apiClient: APIClient, notificationManager: NotificationManager) {
        self.settings = settings
        self.apiClient = apiClient
        self.notificationManager = notificationManager
    }

    var apiConfiguration: APIConfiguration? {
        let baseURL = settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let token = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !baseURL.isEmpty, !token.isEmpty else {
            return nil
        }
        return APIConfiguration(baseURL: baseURL, token: token)
    }

    var latestAssistantMessage: ChatMessage? {
        messages.last(where: { $0.role == .assistant })
    }

    var selectedProfileSlug: String {
        settings.selectedProfileSlug.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var effectiveProfileSlug: String? {
        let selected = selectedProfileSlug
        if !selected.isEmpty {
            return selected
        }
        let fallback = currentUser?.defaultProfileSlug?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !fallback.isEmpty {
            return fallback
        }
        return profiles.first(where: \.isDefault)?.slug ?? profiles.first?.slug
    }

    var activeProfile: AgentProfile? {
        guard let slug = effectiveProfileSlug, !slug.isEmpty else {
            return profiles.first(where: \.isDefault) ?? profiles.first
        }
        return profiles.first(where: { $0.slug == slug })
            ?? profiles.first(where: \.isDefault)
            ?? profiles.first
    }

    var activeProfileTitle: String {
        activeProfile?.name ?? effectiveProfileSlug ?? "Profile"
    }

    func start() async {
        guard !hasStarted else { return }
        hasStarted = true
        await notificationManager.refreshAuthorizationStatus()
        if settings.hasToken {
            await restoreAuthenticatedState(showErrors: false)
        } else {
            authenticationState = .signedOut
            health = .checking
        }
        startPolling()
    }

    func setScenePhase(_ phase: ScenePhase) {
        isSceneActive = phase == .active
        if isSceneActive {
            Task {
                await refreshState(showErrors: false)
            }
        }
    }

    func setChatVisible(_ visible: Bool) {
        isChatVisible = visible
        if visible {
            unreadCount = 0
            updateBadgeCount()
        }
    }

    func filteredCommands(for input: String) -> [LocalCommand] {
        CommandMatcher.filter(input)
    }

    func testServerConnection() async -> Bool {
        do {
            let ok = try await apiClient.health(baseURL: settings.apiURL)
            health = ok ? .healthy : .error("Health check failed")
            errorText = ok ? nil : "The server did not report a healthy status."
            return ok
        } catch {
            health = .error(error.localizedDescription)
            errorText = error.localizedDescription
            return false
        }
    }

    func bootstrapAccount(setupCode: String, displayName: String) async {
        let cleanedCode = setupCode.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanedName = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanedCode.isEmpty, !cleanedName.isEmpty else {
            errorText = "Display name and setup code are required."
            return
        }
        do {
            let result = try await apiClient.bootstrap(
                baseURL: settings.apiURL,
                bootstrapCode: cleanedCode,
                displayName: cleanedName,
                deviceName: UIDevice.current.name
            )
            await finishAuthentication(token: result.token, user: result.user)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func pairAccount(pairCode: String) async {
        let cleaned = pairCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else {
            errorText = "Pair code is required."
            return
        }
        do {
            let result = try await apiClient.pair(
                baseURL: settings.apiURL,
                pairCode: cleaned,
                deviceName: UIDevice.current.name
            )
            await finishAuthentication(token: result.token, user: result.user)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func signInWithToken(_ token: String) async {
        let cleaned = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else {
            errorText = "Access token is required."
            return
        }
        let previous = settings.apiKey
        settings.apiKey = cleaned
        do {
            let user = try await apiClient.authMe(
                config: APIConfiguration(baseURL: settings.apiURL, token: cleaned)
            )
            await finishAuthentication(token: cleaned, user: user)
        } catch {
            settings.apiKey = previous
            errorText = error.localizedDescription
        }
    }

    func restoreAuthenticatedState(showErrors: Bool) async {
        do {
            guard let config = apiConfiguration else {
                authenticationState = .signedOut
                return
            }
            currentUser = try await apiClient.authMe(config: config)
            authenticationState = .signedIn
            errorText = nil
            await refreshState(showErrors: showErrors)
        } catch {
            if showErrors {
                errorText = error.localizedDescription
            }
            authenticationState = .signedOut
            currentUser = nil
        }
    }

    func logout() async {
        settings.eraseAuth()
        currentUser = nil
        profiles = []
        sessionID = nil
        messages = []
        pendingApprovals = []
        pendingPrompts = []
        availableModels = []
        modelName = "default"
        contextTokens = 0
        totalTokens = 0
        sessionCost = 0
        unreadCount = 0
        draft = ""
        pendingComposerAttachments = []
        didPrimeMessageBaseline = false
        errorText = nil
        health = .checking
        activity = .idle
        authenticationState = .signedOut
        updateBadgeCount()
    }

    func useProfile(slug: String?) async {
        let cleaned = slug?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let current = selectedProfileSlug
        if cleaned == current || (cleaned.isEmpty && current.isEmpty) {
            return
        }
        settings.selectedProfileSlug = cleaned
        await applyProfileSelectionChange()
    }

    func sendCurrentDraft() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty || !pendingComposerAttachments.isEmpty else { return }
        draft = ""
        await send(text: text)
    }

    func queueComposerAttachments(urls: [URL]) async {
        do {
            var next = pendingComposerAttachments
            for url in urls where url.isFileURL {
                let gainedAccess = url.startAccessingSecurityScopedResource()
                defer {
                    if gainedAccess {
                        url.stopAccessingSecurityScopedResource()
                    }
                }
                let data = try Data(contentsOf: url)
                let contentType =
                    UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
                    ?? "application/octet-stream"
                next.append(
                    PendingComposerAttachment(
                        id: UUID().uuidString,
                        filename: url.lastPathComponent,
                        contentType: contentType,
                        data: data
                    )
                )
            }
            pendingComposerAttachments = next
        } catch {
            errorText = error.localizedDescription
        }
    }

    func queueComposerAttachments(_ attachments: [PendingComposerAttachment]) {
        guard !attachments.isEmpty else { return }
        pendingComposerAttachments.append(contentsOf: attachments)
    }

    func removeComposerAttachment(id: String) {
        pendingComposerAttachments.removeAll { $0.id == id }
    }

    func send(text: String, modelNameOverride: String? = nil) async {
        if pendingComposerAttachments.isEmpty, await handleCommandIfNeeded(text) {
            return
        }

        guard let config = apiConfiguration else {
            errorText = "You need to sign in first."
            authenticationState = .signedOut
            return
        }

        var optimisticID: String?
        do {
            let id = try await ensureSession(forceNew: false)
            let queuedAttachments = pendingComposerAttachments
            let optimistic = ChatMessage.local(
                role: .user,
                content: text.isEmpty ? "Uploaded attachments." : text
            )
            optimisticID = optimistic.id
            messages.append(optimistic)
            isSending = true
            recalculateActivity()

            _ = try await apiClient.sendMessage(
                config: config,
                sessionID: id,
                text: text,
                attachments: queuedAttachments,
                modelNameOverride: modelNameOverride
            )
            pendingComposerAttachments = []
            await refreshState(showErrors: true)
        } catch {
            if let optimisticID {
                messages.removeAll { $0.id == optimisticID }
            }
            errorText = error.localizedDescription
        }

        isSending = false
        recalculateActivity()
    }

    func createNewSession() async {
        guard let config = apiConfiguration else { return }
        do {
            _ = try await apiClient.executeCommand(
                config: config,
                command: "new",
                agentProfileSlug: effectiveProfileSlug
            )
            sessionID = nil
            messages = []
            pendingApprovals = []
            pendingPrompts = []
            didPrimeMessageBaseline = false
            _ = try await ensureSession(forceNew: false)
            await refreshState(showErrors: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func refreshState(showErrors: Bool) async {
        guard let config = apiConfiguration else {
            authenticationState = .signedOut
            return
        }

        if isRefreshing {
            return
        }

        isRefreshing = true
        defer {
            isRefreshing = false
            recalculateActivity()
        }

        do {
            let user = try await apiClient.authMe(config: config)
            currentUser = user
            let fetchedProfiles = try await apiClient.listProfiles(config: config)
            profiles = fetchedProfiles.sorted { lhs, rhs in
                if lhs.isDefault != rhs.isDefault {
                    return lhs.isDefault && !rhs.isDefault
                }
                return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
            if !selectedProfileSlug.isEmpty && !profiles.contains(where: { $0.slug == selectedProfileSlug && $0.status != "archived" }) {
                settings.selectedProfileSlug = ""
                sessionID = nil
            }
            let id = try await ensureSession(forceNew: false)
            async let snapshot = apiClient.sessionSnapshot(config: config, sessionID: id)
            async let detail = apiClient.sessionDetail(config: config, sessionID: id)
            async let approvals = apiClient.pendingToolRuns(config: config, sessionID: id)
            async let prompts = apiClient.pendingUserPrompts(config: config, sessionID: id)

            let snapshotValue = try await snapshot
            let detailValue = try await detail
            let approvalValue = try await approvals
            let promptValue = try await prompts

            apply(snapshot: snapshotValue, messages: detailValue, approvals: approvalValue, prompts: promptValue)
            if shouldRefreshModels() {
                availableModels = try await apiClient.listModelNames(config: config)
                lastModelRefreshAt = Date()
            }

            authenticationState = .signedIn
            health = .healthy
            errorText = nil
        } catch {
            health = .error(error.localizedDescription)
            if showErrors {
                errorText = error.localizedDescription
            }
        }
    }

    func requestNotifications() async {
        settings.hasPromptedForNotifications = true
        await notificationManager.requestAuthorizationAndRegister()
    }

    func switchModel(to model: String) async {
        guard let config = apiConfiguration, let sessionID else { return }
        do {
            let selected = try await apiClient.setSessionModel(config: config, sessionID: sessionID, modelName: model)
            modelName = selected
            if !availableModels.contains(selected) {
                availableModels.append(selected)
                availableModels.sort()
            }
        } catch {
            errorText = error.localizedDescription
        }
    }

    func approve(_ toolRun: ToolRunStatus) async {
        guard let config = apiConfiguration else { return }
        do {
            try await apiClient.approveToolRun(
                config: config,
                toolRunID: toolRun.id,
                decidedBy: currentUser?.id ?? "ios"
            )
            await refreshState(showErrors: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func deny(_ toolRun: ToolRunStatus) async {
        guard let config = apiConfiguration else { return }
        do {
            try await apiClient.denyToolRun(
                config: config,
                toolRunID: toolRun.id,
                decidedBy: currentUser?.id ?? "ios"
            )
            await refreshState(showErrors: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    func answer(_ prompt: PendingUserPrompt, with answer: String) async {
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        pendingPrompts.removeAll { $0.id == prompt.id }
        await send(text: trimmed)
    }

    func resolvedAttachmentURL(_ attachment: MessageAttachment) -> URL? {
        guard let config = apiConfiguration else { return nil }
        if let downloadURL = attachment.downloadURL {
            return try? apiClient.resolvedURL(config: config, rawURL: downloadURL)
        }
        if let sourceURL = attachment.sourceURL {
            return try? apiClient.resolvedURL(config: config, rawURL: sourceURL)
        }
        return nil
    }

    func fetchAttachmentData(_ attachment: MessageAttachment) async throws -> Data {
        guard let config = apiConfiguration else {
            throw APIClient.APIError.missingAuthToken
        }
        guard let rawURL = attachment.preferredURLString else {
            throw APIClient.APIError.invalidBaseURL
        }
        return try await apiClient.attachmentData(config: config, rawURL: rawURL)
    }

    func downloadAttachmentFile(_ attachment: MessageAttachment) async throws -> URL {
        guard let config = apiConfiguration else {
            throw APIClient.APIError.missingAuthToken
        }
        guard let rawURL = attachment.preferredURLString else {
            throw APIClient.APIError.invalidBaseURL
        }
        return try await apiClient.downloadAttachmentFile(
            config: config,
            rawURL: rawURL,
            suggestedFilename: attachment.filename
        )
    }

    private func finishAuthentication(token: String, user: AuthUser) async {
        settings.apiKey = token
        currentUser = user
        authenticationState = .signedIn
        errorText = nil
        didPrimeMessageBaseline = false
        await refreshState(showErrors: true)
    }

    private func ensureSession(forceNew: Bool) async throws -> String {
        guard let config = apiConfiguration else {
            throw APIClient.APIError.missingAuthToken
        }
        if !forceNew, let sessionID {
            return sessionID
        }
        let id = try await apiClient.createOrResumeSession(
            config: config,
            reuseActive: !forceNew,
            origin: "ios",
            agentProfileSlug: effectiveProfileSlug
        )
        if sessionID != id {
            self.sessionID = id
            didPrimeMessageBaseline = false
            unreadCount = 0
            updateBadgeCount()
        }
        return id
    }

    private func handleCommandIfNeeded(_ text: String) async -> Bool {
        guard text.hasPrefix("/") else { return false }

        let parts = text.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true)
        guard let rawCommand = parts.first else { return false }
        let command = rawCommand.lowercased()
        let argument = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespacesAndNewlines) : ""

        switch command {
        case "/help":
            appendSystemMessage(
                "Available commands:\n" + LocalCommand.all.map { "- \($0.usage): \($0.description)" }.joined(separator: "\n")
            )
            return true
        case "/pair" where !argument.isEmpty && authenticationState == .signedOut:
            await pairAccount(pairCode: argument)
            return true
        default:
            return await runRemoteCommand(command: String(command.dropFirst()), argument: argument)
        }
    }

    private func runRemoteCommand(command: String, argument: String) async -> Bool {
        guard let config = apiConfiguration else {
            errorText = "You need to sign in first."
            return true
        }

        var args: [String: String] = [:]
        switch command {
        case "memory_search":
            if argument.isEmpty {
                appendSystemMessage("Usage: /memory_search <query>")
                return true
            }
            args["query"] = argument
        case "schedule_delete", "schedule_pause", "schedule_resume":
            let key = "job_id"
            if argument.isEmpty {
                appendSystemMessage("Usage: /\(command) <job_id>")
                return true
            }
            args[key] = argument
        case "model":
            if !argument.isEmpty {
                args["model_name"] = argument
            }
        case "machine":
            if !argument.isEmpty {
                args["target_machine"] = argument
            }
        case "profile":
            args["raw"] = argument
        default:
            break
        }

        do {
            let result = try await apiClient.executeCommand(
                config: config,
                command: command,
                args: args,
                agentProfileSlug: effectiveProfileSlug
            )
            appendSystemMessage(result.message.isEmpty ? "Command completed." : result.message)
            if command == "new" {
                sessionID = nil
                messages = []
                pendingApprovals = []
                pendingPrompts = []
                didPrimeMessageBaseline = false
            } else if command == "profile",
                      let data = result.data,
                      data["apply_client_selection"]?.boolValue == true,
                      let nextSlug = data["agent_profile_slug"]?.stringValue,
                      !nextSlug.isEmpty
            {
                settings.selectedProfileSlug = nextSlug
                sessionID = nil
                messages = []
                pendingApprovals = []
                pendingPrompts = []
                didPrimeMessageBaseline = false
            }
            await refreshState(showErrors: true)
        } catch {
            errorText = error.localizedDescription
        }
        return true
    }

    private func appendSystemMessage(_ text: String) {
        messages.append(.local(id: "local-\(UUID().uuidString)", role: .system, content: text))
    }

    private func apply(
        snapshot: SessionSnapshot,
        messages newMessages: [ChatMessage],
        approvals: [ToolRunStatus],
        prompts: [PendingUserPrompt]
    ) {
        contextTokens = snapshot.contextTokens
        totalTokens = snapshot.totalTokens
        sessionCost = snapshot.totalCost
        modelName = snapshot.modelName

        let previousAssistantIDs = Set(messages.filter { $0.role == .assistant }.map(\.id))
        messages = newMessages
        pendingApprovals = approvals
        pendingPrompts = prompts

        if didPrimeMessageBaseline {
            let newAssistantMessages = newMessages.filter {
                $0.role == .assistant && !previousAssistantIDs.contains($0.id)
            }
            if isChatVisible && selectedSection == .chat && isSceneActive {
                unreadCount = 0
            } else if !newAssistantMessages.isEmpty {
                unreadCount += newAssistantMessages.count
                for message in newAssistantMessages {
                    notificationManager.scheduleAssistantReplyNotification(message: message)
                }
            }
        } else {
            unreadCount = 0
            didPrimeMessageBaseline = true
        }

        updateBadgeCount()
        recalculateActivity()
    }

    private func shouldRefreshModels() -> Bool {
        guard let lastModelRefreshAt else { return true }
        return Date().timeIntervalSince(lastModelRefreshAt) > 60
    }

    private func updateBadgeCount() {
        notificationManager.updateBadgeCount(unreadCount + pendingApprovals.count + pendingPrompts.count)
    }

    private func recalculateActivity() {
        if isSending || isRefreshing {
            activity = .thinking
        } else if !pendingApprovals.isEmpty || !pendingPrompts.isEmpty {
            activity = .activeTasks(pendingApprovals.count + pendingPrompts.count)
        } else {
            activity = .idle
        }
    }

    private func startPolling() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if self.authenticationState == .signedIn {
                    await self.refreshState(showErrors: false)
                }
                let interval = self.isSceneActive ? 6.0 : 20.0
                try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            }
        }
    }

    private func applyProfileSelectionChange() async {
        sessionID = nil
        messages = []
        pendingApprovals = []
        pendingPrompts = []
        didPrimeMessageBaseline = false
        unreadCount = 0
        updateBadgeCount()
        await refreshState(showErrors: true)
    }
}
