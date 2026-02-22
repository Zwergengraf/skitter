import AppKit
import SwiftUI
import os

struct ChatView: View {
    @ObservedObject var state: AppState
    var onOpenConversation: () -> Void
    @Environment(\.colorScheme) private var colorScheme
    @State private var visibleLimit: Int = 40
    @State private var onboardingChecking: Bool = false
    @State private var onboardingStatusText: String?
    @State private var onboardingDisplayName: String = ""
    @State private var onboardingSetupCode: String = ""
    @State private var onboardingPairCode: String = ""
    @State private var isNearBottom: Bool = true
    private static let progressMessageID = "temporary-progress-message"
    private static let bottomAnchorID = "chat-bottom-anchor"
    private static let relativeTimeFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter
    }()

    private var hiddenCount: Int {
        max(0, state.messages.count - visibleLimit)
    }

    private var displayedMessages: [ChatMessage] {
        if state.messages.count <= visibleLimit {
            return state.messages
        }
        return Array(state.messages.suffix(visibleLimit))
    }

    private var filteredCommands: [LocalCommand] {
        state.filteredCommands(for: state.draft)
    }

    private var panelBackground: Color {
        Color(nsColor: .controlBackgroundColor).opacity(colorScheme == .dark ? 0.45 : 0.80)
    }

    private var panelStroke: Color {
        Color(nsColor: .separatorColor).opacity(colorScheme == .dark ? 0.45 : 0.30)
    }

    private var assistantBubbleColor: Color {
        if colorScheme == .dark {
            return Color(red: 0.19, green: 0.30, blue: 0.46).opacity(0.62)
        }
        return Color(red: 0.88, green: 0.94, blue: 1.00)
    }

    private var userBubbleColor: Color {
        if colorScheme == .dark {
            return Color.white.opacity(0.08)
        }
        return Color.black.opacity(0.035)
    }

    private var bubbleStrokeColor: Color {
        Color(nsColor: .separatorColor).opacity(colorScheme == .dark ? 0.50 : 0.20)
    }

    var body: some View {
        VStack(spacing: 0) {
            headerBar
            Divider()

            if let banner = state.errorBanner {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                    Text(banner)
                        .font(.caption)
                        .lineLimit(2)
                    Spacer()
                    Button("Reconnect") {
                        Task { await state.reconnect() }
                    }
                    .buttonStyle(.bordered)
                    Button("Dismiss") {
                        state.dismissErrorBanner()
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color.red.opacity(colorScheme == .dark ? 0.16 : 0.08))
                Divider()
            }

            if !state.pendingToolApprovals.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Label("Tool approval required", systemImage: "hand.raised.fill")
                            .font(.caption.bold())
                        Spacer()
                        Text("\(state.pendingToolApprovals.count)")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                    ForEach(state.pendingToolApprovals, id: \.id) { toolRun in
                        toolApprovalCard(toolRun)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color.orange.opacity(colorScheme == .dark ? 0.16 : 0.08))
                Divider()
            }

            if state.shouldShowOnboarding {
                onboardingCard()
                Divider()
            }

            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if hiddenCount > 0 {
                            Button("Load \(min(40, hiddenCount)) older messages (\(hiddenCount) remaining)") {
                                visibleLimit += 40
                            }
                            .buttonStyle(.bordered)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.bottom, 6)
                        }
                        ForEach(displayedMessages) { message in
                            messageRow(message)
                        }
                        if !state.progressStatusText.isEmpty {
                            progressMessageRow()
                        }
                        Color.clear
                            .frame(height: 12)
                            .id(Self.bottomAnchorID)
                    }
                    .padding(.horizontal, 12)
                    .padding(.top, 12)
                }
                .background(Color.clear)
                .background(
                    ChatScrollMonitor { nearBottom in
                        if nearBottom != isNearBottom {
                            isNearBottom = nearBottom
                        }
                    }
                )
                .onAppear {
                    scrollToBottom(proxy, animated: false)
                }
                .onChange(of: state.messages.count) { oldValue, newValue in
                    guard newValue > oldValue else { return }
                    guard isNearBottom else { return }
                    scrollToBottom(proxy, animated: false)
                }
                .onChange(of: state.chatOpenSignal) { _, _ in
                    scrollToBottom(proxy, animated: false)
                }
            }

            Divider()

            VStack(spacing: 8) {
                if !filteredCommands.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(filteredCommands.prefix(6)) { cmd in
                            Button {
                                state.draft = cmd.usage
                                if !cmd.usage.contains(" ") {
                                    state.draft += " "
                                }
                            } label: {
                                HStack {
                                    Text(cmd.usage)
                                        .font(.caption.monospaced())
                                    Text(cmd.description)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Spacer()
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(panelBackground))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(panelStroke, lineWidth: 1)
                    )
                }

                HStack(alignment: .bottom, spacing: 8) {
                    ZStack(alignment: .topLeading) {
                        if state.draft.isEmpty {
                            Text("Message")
                                .foregroundStyle(.secondary)
                                .padding(.leading, 12)
                                .padding(.top, 11)
                        }
                        CommandInputTextView(
                            text: $state.draft,
                            onSubmit: { Task { await state.sendCurrentDraft() } },
                            onEscape: {
                                state.draft = ""
                            }
                        )
                    }
                    .frame(minHeight: 54, idealHeight: 96, maxHeight: 130)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(panelBackground)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(panelStroke, lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                    VStack(spacing: 8) {
                        Button(action: {
                            Task { await state.toggleTranscription() }
                        }) {
                            Image(systemName: state.isTranscribing ? "stop.circle.fill" : (state.isTranscriptionStarting ? "waveform.circle.fill" : "mic.circle.fill"))
                                .font(.title2)
                                .foregroundStyle(state.isTranscribing ? .red : (state.isTranscriptionStarting ? .orange : .secondary))
                        }
                        .buttonStyle(.plain)
                        .disabled(state.isTranscriptionStarting)
                        .help(state.isTranscribing ? "Stop voice transcription" : (state.isTranscriptionStarting ? "Starting voice transcription…" : "Start voice transcription"))

                        Button(action: {
                            Task { await state.sendCurrentDraft() }
                        }) {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.title2)
                        }
                        .buttonStyle(.plain)
                        .disabled(state.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }

                HStack {
                    Text(keyboardHintText)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button(action: onOpenConversation) {
                        Label(
                            "Conversation Mode",
                            systemImage: state.isConversationWindowVisible ? "waveform.circle.fill" : "waveform"
                        )
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .help(state.isConversationWindowVisible ? "Close conversation mode window" : "Open conversation mode window")
                }
            }
            .padding(12)

            Divider()

            HStack(spacing: 10) {
                Text("Model:")
                    .lineLimit(1)
                Menu {
                    if state.availableModels.isEmpty {
                        Text("No models available")
                    } else {
                        ForEach(state.availableModels, id: \.self) { model in
                            Button {
                                Task { await state.switchModel(to: model) }
                            } label: {
                                if model == state.modelName {
                                    Label(model, systemImage: "checkmark")
                                } else {
                                    Text(model)
                                }
                            }
                        }
                    }
                } label: {
                    Text(state.modelName)
                        .lineLimit(1)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.secondary.opacity(0.10))
                    )
                }
                .menuStyle(.borderlessButton)
                Text(
                    "Tokens: \(state.totalTokens)  |  Context: \(state.contextTokens)  |  Cost: $\(String(format: "%.2f", state.sessionCost))"
                )
                .lineLimit(1)
                .truncationMode(.middle)
                .minimumScaleFactor(0.85)
                Spacer()
            }
            .font(.caption.monospaced())
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
        .frame(
            minWidth: 500,
            minHeight: 620
        )
        .background(
            ZStack {
                BackdropBlurView(material: .hudWindow, blendingMode: .behindWindow, emphasized: true)
                Color(nsColor: .windowBackgroundColor).opacity(colorScheme == .dark ? 0.56 : 0.66)
                Color(nsColor: .textBackgroundColor).opacity(colorScheme == .dark ? 0.15 : 0.19)
            }
        )
        .task {
            do {
                _ = try await state.ensureSession(forceNew: false)
                state.markChatOpened()
            } catch {
                // Status strip already shows health errors.
            }
        }
    }

    @ViewBuilder
    private var headerBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "bolt.circle.fill")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color.accentColor)
            Text("Skitter")
                .font(.subheadline.weight(.semibold))
            Spacer(minLength: 8)
            Button {
                state.toggleChatPinned()
            } label: {
                Image(systemName: state.isChatPinned ? "pin.fill" : "pin")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(state.isChatPinned ? Color.green : Color.secondary)
                    .frame(width: 20, height: 20)
                    .background(
                        Circle()
                            .fill(Color.secondary.opacity(colorScheme == .dark ? 0.22 : 0.12))
                    )
            }
            .buttonStyle(.plain)
            .help(state.isChatPinned ? "Unpin chat window" : "Pin chat window")
            statusChip(label: state.health.label.capitalized, color: healthChipColor)
            statusChip(label: state.activity.label.capitalized, color: activityChipColor)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 4)
        .frame(minHeight: 30, maxHeight: 30)
        .background(.ultraThinMaterial)
    }

    @ViewBuilder
    private func onboardingCard() -> some View {
        let apiURLBinding = Binding<String>(
            get: { state.settings.apiURL },
            set: { state.settings.apiURL = $0 }
        )
        let apiKeyBinding = Binding<String>(
            get: { state.settings.apiKey },
            set: { state.settings.apiKey = $0 }
        )
        VStack(alignment: .leading, spacing: 10) {
            Text("Welcome to Skitter")
                .font(.headline)
            Text("Connect with an existing access token, or bootstrap/pair this device.")
                .font(.caption)
                .foregroundStyle(.secondary)

            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    Text("API URL")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                    TextField("http://localhost:8000", text: apiURLBinding)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Access Token")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                    SecureField("Optional (set by bootstrap/pair)", text: apiKeyBinding)
                        .textFieldStyle(.roundedBorder)
                }
            }

            HStack(spacing: 8) {
                Button(onboardingChecking ? "Testing..." : "Test Connection") {
                    Task {
                        onboardingChecking = true
                        onboardingStatusText = nil
                        await state.reconnect()
                        onboardingChecking = false
                        if state.hasWorkingConnection {
                            onboardingStatusText = "Connected."
                        } else {
                            onboardingStatusText = state.errorBanner ?? "Connection failed. Check URL and API key."
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(onboardingChecking)

                if state.hasWorkingConnection {
                    Label("Connected", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                } else {
                    Label("Not connected", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            Divider()

            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    Text("Name")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                    TextField("Your display name", text: $onboardingDisplayName)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Setup Code")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                    SecureField("First-time setup code", text: $onboardingSetupCode)
                        .textFieldStyle(.roundedBorder)
                }
            }
            HStack(spacing: 8) {
                Button("Register & Connect") {
                    Task {
                        await state.bootstrapAccount(
                            setupCode: onboardingSetupCode,
                            displayName: onboardingDisplayName
                        )
                        onboardingStatusText = state.errorBanner ?? "Registered and connected."
                    }
                }
                .buttonStyle(.bordered)
                Spacer()
            }

            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    Text("Pair Code")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 86, alignment: .leading)
                    TextField("ABCD-1234", text: $onboardingPairCode)
                        .textFieldStyle(.roundedBorder)
                }
            }
            HStack(spacing: 8) {
                Button("Pair Existing Account") {
                    Task {
                        await state.pairAccount(pairCode: onboardingPairCode)
                        onboardingStatusText = state.errorBanner ?? "Paired and connected."
                    }
                }
                .buttonStyle(.bordered)
                Spacer()
            }

            if let onboardingStatusText, !onboardingStatusText.isEmpty {
                Text(onboardingStatusText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color.secondary.opacity(0.08))
    }

    @ViewBuilder
    private func messageRow(_ message: ChatMessage) -> some View {
        let isUser = message.role == .user
        let bubble = VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label(for: message.role))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            }

            MarkdownMessageText(message.content.isEmpty ? "(empty)" : message.content)

            if !message.attachments.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(message.attachments.enumerated()), id: \.offset) { _, attachment in
                        attachmentView(attachment)
                    }
                }
            }
        }
        .padding(11)
        .frame(maxWidth: 470, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(isUser ? userBubbleColor : assistantBubbleColor)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(bubbleStrokeColor, lineWidth: 1)
                )
        )
        .contextMenu {
            if message.role == .assistant {
                Button("Copy Reply") {
                    copyToPasteboard(message.content)
                }
                Button("Copy Reply as Markdown") {
                    copyToPasteboard(markdownForMessage(message))
                }
            }
        }

        HStack(alignment: .bottom) {
            if isUser {
                Spacer(minLength: 44)
            }
            bubble
            if !isUser {
                Spacer(minLength: 44)
            }
        }
        .id(message.id)
    }

    @ViewBuilder
    private func attachmentView(_ attachment: MessageAttachment) -> some View {
        let url = resolvedURL(for: attachment)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "paperclip")
                    .font(.caption)
                Text(attachment.filename)
                    .font(.caption)
                    .lineLimit(1)
                Spacer()
                if let url {
                    Button("Open") {
                        Task { await state.openAttachment(url: url, preferredName: attachment.filename) }
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                    Button("Download") {
                        Task { await state.downloadAttachment(url: url, preferredName: attachment.filename) }
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                }
            }
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(panelBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(panelStroke, lineWidth: 1)
                )
        )
    }

    @ViewBuilder
    private func toolApprovalCard(_ toolRun: ToolRunStatus) -> some View {
        let isBusy = state.isDecidingToolRun(id: toolRun.id)
        VStack(alignment: .leading, spacing: 6) {
            Text(toolRun.tool)
                .font(.caption.monospaced())
            Text(approvalDetailLine(for: toolRun))
                .font(.caption2)
                .foregroundStyle(.secondary)
            if !toolRun.secretRefs.isEmpty {
                Text("Secrets: \(toolRun.secretRefs.joined(separator: ", "))")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("Parameters")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                ScrollView {
                    Text(toolRun.inputPrettyJSON())
                        .font(.caption.monospaced())
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxWidth: .infinity, minHeight: 70, maxHeight: 170)
                .padding(6)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color.black.opacity(0.06)))
            }
            HStack(spacing: 8) {
                Button {
                    Task { await state.approveToolRun(id: toolRun.id) }
                } label: {
                    Text(isBusy ? "Working..." : "Approve")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isBusy)

                Button {
                    Task { await state.denyToolRun(id: toolRun.id) }
                } label: {
                    Text("Deny")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(isBusy)
            }
        }
        .padding(9)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(panelBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(panelStroke, lineWidth: 1)
                )
        )
    }

    @ViewBuilder
    private func progressMessageRow() -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Skitter")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                HStack(spacing: 5) {
                    ProgressView()
                        .controlSize(.small)
                    Text("temporary")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                ForEach(state.progressStatusText.split(separator: "\n"), id: \.self) { line in
                    Text(String(line))
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(panelBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(panelStroke, style: StrokeStyle(lineWidth: 1, dash: [5, 3]))
                )
        )
        .id(Self.progressMessageID)
    }

    private var healthChipColor: Color {
        switch state.health {
        case .checking:
            return .orange
        case .healthy:
            return .green
        case .error:
            return .red
        }
    }

    private var activityChipColor: Color {
        switch state.activity {
        case .idle:
            return .secondary
        case .thinking:
            return .blue
        case .activeTasks:
            return .orange
        }
    }

    @ViewBuilder
    private func statusChip(label: String, color: Color) -> some View {
        Text(label)
            .font(.caption2.weight(.medium))
            .lineLimit(1)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                Capsule()
                    .fill(color.opacity(colorScheme == .dark ? 0.22 : 0.14))
                    .overlay(
                        Capsule()
                            .stroke(color.opacity(colorScheme == .dark ? 0.55 : 0.30), lineWidth: 1)
                    )
            )
            .foregroundStyle(colorScheme == .dark ? .white : color)
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        let targetID = Self.bottomAnchorID
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.15)) {
                    proxy.scrollTo(targetID, anchor: .bottom)
                }
            } else {
                proxy.scrollTo(targetID, anchor: .bottom)
            }
        }
    }

    private func label(for role: ChatRole) -> String {
        switch role {
        case .user:
            return "You"
        case .assistant:
            return "Skitter"
        case .system:
            return "System"
        case .other:
            return "Message"
        }
    }

    private var keyboardHintText: String {
        if state.isTranscriptionStarting {
            return "Starting local Whisper… | Enter: send | Shift+Enter: newline"
        }
        if state.isTranscribing {
            return "Listening with local Whisper… Tap mic to stop | Enter: send | Shift+Enter: newline"
        }
        if !state.transcriptionStatusText.isEmpty {
            return "\(state.transcriptionStatusText) | Enter: send | Shift+Enter: newline"
        }
        return "Enter: send | Shift+Enter: newline"
    }

    private func approvalDetailLine(for toolRun: ToolRunStatus) -> String {
        let who: String
        if let requestedBy = toolRun.requestedBy?.trimmingCharacters(in: .whitespacesAndNewlines), !requestedBy.isEmpty {
            who = " by \(requestedBy)"
        } else {
            who = ""
        }
        let relative = Self.relativeTimeFormatter.localizedString(for: toolRun.createdAt, relativeTo: Date())
        return "Requested\(who) \(relative)"
    }

    private func copyToPasteboard(_ text: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
    }

    private func markdownForMessage(_ message: ChatMessage) -> String {
        var lines = [message.content]
        if !message.attachments.isEmpty {
            lines.append("")
            for attachment in message.attachments {
                if let url = resolvedURL(for: attachment) {
                    if isImageAttachment(attachment) {
                        lines.append("![\(attachment.filename)](\(url.absoluteString))")
                    } else {
                        lines.append("[\(attachment.filename)](\(url.absoluteString))")
                    }
                } else {
                    lines.append("- \(attachment.filename)")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    private func resolvedURL(for attachment: MessageAttachment) -> URL? {
        if let download = attachment.downloadURL?.trimmingCharacters(in: .whitespacesAndNewlines), !download.isEmpty {
            if let absolute = URL(string: download), absolute.scheme != nil {
                return absolute
            }
            let base = settingsBaseURL()
            return URL(string: download, relativeTo: base)?.absoluteURL
        }
        if let source = attachment.sourceURL?.trimmingCharacters(in: .whitespacesAndNewlines), !source.isEmpty {
            if let absolute = URL(string: source), absolute.scheme != nil {
                return absolute
            }
            let base = settingsBaseURL()
            return URL(string: source, relativeTo: base)?.absoluteURL
        }
        return nil
    }

    private func isImageAttachment(_ attachment: MessageAttachment) -> Bool {
        if attachment.contentType.lowercased().hasPrefix("image/") {
            return true
        }
        let lower = attachment.filename.lowercased()
        return lower.hasSuffix(".png") || lower.hasSuffix(".jpg") || lower.hasSuffix(".jpeg") || lower.hasSuffix(".webp") || lower.hasSuffix(".gif")
    }

    private func settingsBaseURL() -> URL {
        let base = state.settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return URL(string: base) ?? URL(string: "http://localhost:8000")!
    }
}

private struct AttachmentThumbnailView: View {
    @ObservedObject var state: AppState
    let url: URL
    let maxWidth: CGFloat

    private static let imageCache: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 120
        return cache
    }()

    @State private var image: NSImage?
    @State private var loading = false

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: maxWidth, height: 120)
                    .clipped()
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            } else {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.secondary.opacity(0.15))
                    .frame(width: maxWidth, height: 120)
                    .overlay(loading ? AnyView(ProgressView()) : AnyView(EmptyView()))
            }
        }
        .task(id: url.absoluteString) {
            await load()
        }
    }

    private func load() async {
        let cacheKey = url.absoluteString as NSString
        if let cached = Self.imageCache.object(forKey: cacheKey) {
            image = cached
            return
        }

        loading = true
        defer { loading = false }
        guard let data = await state.fetchAttachmentData(url: url) else { return }
        let decodedImage = await Task.detached(priority: .utility) {
            NSImage(data: data)
        }.value
        guard !Task.isCancelled else { return }
        guard let decodedImage else { return }
        Self.imageCache.setObject(decodedImage, forKey: cacheKey)
        image = decodedImage
    }
}

private struct ChatScrollMonitor: NSViewRepresentable {
    var onNearBottomChange: (Bool) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onNearBottomChange: onNearBottomChange)
    }

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        context.coordinator.attach(to: view)
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.onNearBottomChange = onNearBottomChange
        context.coordinator.attach(to: nsView)
    }

    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) {
        coordinator.detach()
    }

    final class Coordinator {
        private static let logger = Logger(subsystem: "io.skitter.menubar", category: "scroll")

        var onNearBottomChange: (Bool) -> Void

        private weak var scrollView: NSScrollView?
        private weak var observedDocumentView: NSView?
        private var observers: [NSObjectProtocol] = []
        private var lastNearBottom: Bool?

        init(onNearBottomChange: @escaping (Bool) -> Void) {
            self.onNearBottomChange = onNearBottomChange
        }

        func attach(to view: NSView) {
            guard let resolved = Self.findScrollView(startingFrom: view) else { return }

            let didChangeTarget = scrollView !== resolved || observedDocumentView !== resolved.documentView
            if didChangeTarget {
                removeObservers()
                scrollView = resolved
                observedDocumentView = resolved.documentView
                configure(scrollView: resolved)
                installObservers(scrollView: resolved)
            } else {
                configure(scrollView: resolved)
            }
            publishMetrics()
        }

        func detach() {
            removeObservers()
            scrollView = nil
            observedDocumentView = nil
            lastNearBottom = nil
        }

        private func configure(scrollView: NSScrollView) {
            scrollView.verticalScrollElasticity = .none
            scrollView.horizontalScrollElasticity = .none
            scrollView.automaticallyAdjustsContentInsets = false
            scrollView.contentInsets = NSEdgeInsets()
            scrollView.contentView.postsBoundsChangedNotifications = true
            scrollView.documentView?.postsFrameChangedNotifications = true
        }

        private func installObservers(scrollView: NSScrollView) {
            let boundsObserver = NotificationCenter.default.addObserver(
                forName: NSView.boundsDidChangeNotification,
                object: scrollView.contentView,
                queue: .main
            ) { [weak self] _ in
                self?.publishMetrics()
            }
            observers.append(boundsObserver)

            if let documentView = scrollView.documentView {
                let frameObserver = NotificationCenter.default.addObserver(
                    forName: NSView.frameDidChangeNotification,
                    object: documentView,
                    queue: .main
                ) { [weak self] _ in
                    self?.publishMetrics()
                }
                observers.append(frameObserver)
            }
        }

        private func removeObservers() {
            for observer in observers {
                NotificationCenter.default.removeObserver(observer)
            }
            observers.removeAll()
        }

        private func publishMetrics() {
            guard let scrollView else { return }
            let clipBounds = scrollView.contentView.bounds
            let visibleHeight = max(clipBounds.height, 1)
            let documentHeight = max(scrollView.documentView?.bounds.height ?? 0, visibleHeight)
            let maxOffsetY = max(0, documentHeight - visibleHeight)
            let clampedOffsetY = min(max(0, clipBounds.origin.y), maxOffsetY)
            let distanceFromBottom = maxOffsetY - clampedOffsetY
            let nearBottom = distanceFromBottom <= 12

            if let previous = lastNearBottom, previous != nearBottom {
                Self.logger.debug(
                    "Scroll edge changed. nearBottom=\(nearBottom) offset=\(clampedOffsetY, format: .fixed(precision: 1)) max=\(maxOffsetY, format: .fixed(precision: 1))"
                )
            }

            if lastNearBottom != nearBottom {
                lastNearBottom = nearBottom
                onNearBottomChange(nearBottom)
            }
        }

        private static func findScrollView(startingFrom view: NSView) -> NSScrollView? {
            if let enclosing = view.enclosingScrollView {
                return enclosing
            }
            var current: NSView? = view
            while let candidate = current {
                if let scrollView = candidate as? NSScrollView {
                    return scrollView
                }
                if let enclosing = candidate.enclosingScrollView {
                    return enclosing
                }
                current = candidate.superview
            }
            return nil
        }
    }
}
