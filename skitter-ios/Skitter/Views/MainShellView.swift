import SwiftUI
import Speech
import UIKit

private enum RelativeTimeFormatters {
    static let approvals: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter
    }()
}

private struct RecognitionLanguageOption: Identifiable, Hashable {
    let id: String
    let title: String

    static let available: [RecognitionLanguageOption] = {
        let supported = Set(SFSpeechRecognizer.supportedLocales().map(\.identifier))
        let preferredIdentifiers = [
            Locale.current.identifier,
            "en-US",
            "en-GB",
            "de-DE",
            "fr-FR",
            "es-ES",
            "it-IT",
            "nl-NL",
            "pt-BR",
            "ja-JP",
            "zh-CN",
        ]

        var identifiers: [String] = []
        for identifier in preferredIdentifiers where supported.contains(identifier) && !identifiers.contains(identifier) {
            identifiers.append(identifier)
        }

        return identifiers.map { identifier in
            RecognitionLanguageOption(
                id: identifier,
                title: Locale.current.localizedString(forIdentifier: identifier) ?? identifier
            )
        }
    }()

    static func title(for identifier: String) -> String {
        let cleaned = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            return "System Default"
        }
        return available.first(where: { $0.id == cleaned })?.title
            ?? Locale.current.localizedString(forIdentifier: cleaned)
            ?? cleaned
    }

    static var currentLocaleDescription: String {
        Locale.current.localizedString(forIdentifier: Locale.current.identifier) ?? Locale.current.identifier
    }
}

struct MainShellView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @ObservedObject var notifications: NotificationManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var prefersSplitView: Bool {
        UIDevice.current.userInterfaceIdiom == .pad || horizontalSizeClass == .regular
    }

    var body: some View {
        Group {
            if prefersSplitView {
                splitView
            } else {
                tabView
            }
        }
        .task {
            if !settings.hasPromptedForNotifications && notifications.authorizationStatus == .notDetermined {
                await model.requestNotifications()
            }
        }
    }

    private var splitView: some View {
        NavigationSplitView {
            List {
                ForEach(AppSection.allCases) { section in
                    Button {
                        model.selectedSection = section
                    } label: {
                        SidebarRow(
                            title: section.title,
                            systemImage: section.systemImage,
                            badge: badgeValue(for: section)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .navigationTitle("Skitter")
        } detail: {
            detailView(for: model.selectedSection)
        }
    }

    private var tabView: some View {
        TabView(selection: $model.selectedSection) {
            NavigationStack {
                detailView(for: .chat)
            }
            .tabItem {
                Label("Chat", systemImage: "bubble.left.and.bubble.right")
            }
            .badge(model.unreadCount)
            .tag(AppSection.chat)

            NavigationStack {
                detailView(for: .approvals)
            }
            .tabItem {
                Label("Approvals", systemImage: "checkmark.shield")
            }
            .badge(model.pendingApprovals.count)
            .tag(AppSection.approvals)

            NavigationStack {
                detailView(for: .voice)
            }
            .tabItem {
                Label("Voice", systemImage: "waveform")
            }
            .tag(AppSection.voice)

            NavigationStack {
                detailView(for: .settings)
            }
            .tabItem {
                Label("Settings", systemImage: "gearshape")
            }
            .tag(AppSection.settings)
        }
    }

    @ViewBuilder
    private func detailView(for section: AppSection) -> some View {
        switch section {
        case .chat:
            ChatScreen(model: model, settings: settings, notifications: notifications)
        case .approvals:
            ApprovalsScreen(model: model)
        case .voice:
            VoiceScreen(model: model, settings: settings, notifications: notifications)
        case .settings:
            SettingsScreen(model: model, settings: settings, notifications: notifications)
        }
    }

    private func badgeValue(for section: AppSection) -> Int? {
        switch section {
        case .chat:
            return model.unreadCount == 0 ? nil : model.unreadCount
        case .approvals:
            return model.pendingApprovals.isEmpty ? nil : model.pendingApprovals.count
        case .voice, .settings:
            return nil
        }
    }
}

private struct SidebarRow: View {
    let title: String
    let systemImage: String
    let badge: Int?

    var body: some View {
        HStack {
            Label(title, systemImage: systemImage)
            Spacer()
            if let badge {
                Text("\(badge)")
                    .font(.caption2.weight(.bold))
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(Color.accentColor.opacity(0.14), in: Capsule())
            }
        }
    }
}

private struct ChatScreen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @ObservedObject var notifications: NotificationManager
    @Environment(\.openURL) private var openURL
    @StateObject private var speechController = SpeechCaptureController()
    @StateObject private var speaker = VoicePlaybackController()
    @State private var showsDetails = false

    private let bottomAnchorID = "chat-bottom-anchor"

    private var filteredCommands: [LocalCommand] {
        model.filteredCommands(for: model.draft)
    }

    private var quickVoiceButtonIcon: String {
        if speechController.isListening {
            return "stop.circle.fill"
        }
        if speechController.isPreparing {
            return "waveform.circle.fill"
        }
        return "mic.circle.fill"
    }

    private var quickVoiceButtonTint: Color {
        if speechController.isListening {
            return .red
        }
        if speechController.isPreparing {
            return .orange
        }
        return .accentColor
    }

    var body: some View {
        VStack(spacing: 0) {
            if notifications.authorizationStatus == .notDetermined {
                notificationPrompt
            }

            if let error = model.errorText, !error.isEmpty {
                errorBanner(error)
            }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if !model.pendingApprovals.isEmpty {
                            InlineApprovalSection(model: model)
                        }

                        if model.messages.isEmpty && !model.isSending {
                            EmptyChatState()
                        } else {
                            ForEach(model.messages) { message in
                                MessageBubble(
                                    message: message,
                                    model: model,
                                    settings: settings,
                                    speaker: speaker,
                                    openURL: openURL
                                )
                                .id(message.id)
                            }
                        }

                        if model.isSending {
                            ThinkingIndicatorCard()
                        }

                        Color.clear
                            .frame(height: 1)
                            .id(bottomAnchorID)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 18)
                }
                .background(Color(uiColor: .systemGroupedBackground))
                .onChange(of: model.messages.count) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: model.pendingApprovals.count) { _, _ in
                    scrollToBottom(proxy, animated: false)
                }
                .onChange(of: model.isSending) { _, _ in
                    scrollToBottom(proxy, animated: false)
                }
            }

            Divider()

            VStack(spacing: 12) {
                if !filteredCommands.isEmpty {
                    commandStrip
                }

                if speechController.isListening || speechController.isPreparing || speechController.errorText != nil || !speechController.transcript.isEmpty {
                    quickVoiceStatus
                }

                HStack(alignment: .bottom, spacing: 12) {
                    composer

                    VStack(spacing: 10) {
                        Button {
                            Task {
                                await toggleQuickVoice()
                            }
                        } label: {
                            Image(systemName: quickVoiceButtonIcon)
                                .font(.system(size: 28, weight: .medium))
                                .foregroundStyle(quickVoiceButtonTint)
                        }
                        .buttonStyle(.plain)
                        .disabled(speechController.isPreparing || model.isSending)
                        .accessibilityLabel(speechController.isListening ? "Stop voice dictation" : "Start voice dictation")

                        Button {
                            if speechController.isListening {
                                speechController.stopListening(clearTranscript: false)
                            }
                            Task {
                                await model.sendCurrentDraft()
                            }
                        } label: {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.system(size: 30))
                        }
                        .buttonStyle(.plain)
                        .disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isSending)
                    }
                }
                .padding(.horizontal, 16)

                HStack(spacing: 8) {
                    StatusChip(label: model.health.label, tint: healthTint)
                    StatusChip(label: model.activity.label, tint: activityTint)
                    Spacer()
                    Label(model.modelName, systemImage: "cpu")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 14)
            }
            .background(.thinMaterial)
        }
        .navigationTitle("Skitter")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    Task {
                        await model.createNewSession()
                    }
                } label: {
                    Image(systemName: "plus.bubble")
                }

                Button {
                    showsDetails = true
                } label: {
                    Image(systemName: "slider.horizontal.3")
                }
            }
        }
        .sheet(isPresented: $showsDetails) {
            SessionDetailsSheet(model: model)
                .presentationDetents([.medium, .large])
        }
        .onAppear {
            speechController.setRecognitionLocaleIdentifier(settings.effectiveSpeechRecognitionLocaleIdentifier)
            model.setChatVisible(true)
        }
        .onDisappear {
            model.setChatVisible(false)
            speechController.stopListening(clearTranscript: false)
            speaker.stop()
        }
        .onChange(of: settings.speechRecognitionLocaleIdentifier) { _, _ in
            speechController.setRecognitionLocaleIdentifier(settings.effectiveSpeechRecognitionLocaleIdentifier)
        }
    }

    private var commandStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(filteredCommands.prefix(6)) { command in
                    Button {
                        model.draft = command.usage + (command.usage.contains(" ") ? "" : " ")
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(command.usage)
                                .font(.caption.monospaced())
                            Text(command.description)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .background(
                            Color(uiColor: .secondarySystemBackground),
                            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 16)
        }
    }

    private var composer: some View {
        ZStack(alignment: .topLeading) {
            if model.draft.isEmpty {
                Text(speechController.isListening ? "Listening for your prompt..." : "Message Skitter")
                    .foregroundStyle(.secondary)
                    .padding(.top, 14)
                    .padding(.leading, 18)
            }
            TextEditor(text: $model.draft)
                .frame(minHeight: 54, maxHeight: 120)
                .padding(8)
                .scrollContentBackground(.hidden)
                .background(Color.clear)
                .disabled(speechController.isPreparing)
        }
        .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var quickVoiceStatus: some View {
        HStack(spacing: 12) {
            Image(systemName: speechController.errorText == nil ? "waveform.badge.mic" : "exclamationmark.triangle.fill")
                .foregroundStyle(speechController.errorText == nil ? quickVoiceButtonTint : .orange)

            VStack(alignment: .leading, spacing: 3) {
                Text(speechController.statusText)
                    .font(.subheadline.weight(.semibold))

                if let error = speechController.errorText, !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if !speechController.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Text(speechController.transcript)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                } else {
                    Text("Skitter will send the transcript after \(settings.conversationSilenceSeconds, specifier: "%.1f") seconds of silence.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            if !speechController.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Button("Send Now") {
                    speechController.submitCurrentTranscript()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(model.isSending)
            }
        }
        .padding(12)
        .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .padding(.horizontal, 16)
    }

    private var notificationPrompt: some View {
        HStack(spacing: 12) {
            Image(systemName: "bell.badge")
                .foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 3) {
                Text("Turn on notifications")
                    .font(.subheadline.weight(.semibold))
                Text("Keep unread replies and approval requests visible even when the app is in the background.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Enable") {
                Task {
                    await model.requestNotifications()
                }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(14)
        .background(Color.accentColor.opacity(0.08))
    }

    private func errorBanner(_ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(text)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button("Refresh") {
                Task {
                    await model.refreshState(showErrors: true)
                }
            }
            .buttonStyle(.bordered)
        }
        .padding(12)
        .background(Color.orange.opacity(0.08))
    }

    private var healthTint: Color {
        switch model.health {
        case .checking:
            return .orange
        case .healthy:
            return .green
        case .error:
            return .red
        }
    }

    private var activityTint: Color {
        switch model.activity {
        case .idle:
            return .secondary
        case .thinking:
            return .blue
        case .activeTasks:
            return .orange
        }
    }

    private func toggleQuickVoice() async {
        if speechController.isListening || speechController.isPreparing {
            speechController.stopListening(clearTranscript: false)
            return
        }

        await speechController.startListening(
            silenceInterval: settings.conversationSilenceSeconds,
            autoSubmitOnSilence: true,
            onTranscript: { transcript in
                model.draft = transcript
            },
            onSegment: { transcript in
                await model.send(text: transcript)
            }
        )
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        let action = {
            proxy.scrollTo(bottomAnchorID, anchor: .bottom)
        }
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.2)) {
                    action()
                }
            } else {
                action()
            }
        }
    }
}

private struct EmptyChatState: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "bolt.circle")
                .font(.system(size: 42))
                .foregroundStyle(Color.accentColor)
            Text("Your active session will appear here.")
                .font(.headline)
            Text("Message Skitter below, dictate a prompt with the microphone, or open the dedicated voice mode for a hands-free flow.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 44)
    }
}

private struct InlineApprovalSection: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Approval required", systemImage: "hand.raised.fill")
                    .font(.headline)
                Spacer()
                Text("\(model.pendingApprovals.count)")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Color.orange.opacity(0.14), in: Capsule())
                    .foregroundStyle(.orange)
            }

            Text("Skitter is waiting on these tool decisions before it can keep moving.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            ForEach(model.pendingApprovals) { toolRun in
                ApprovalCard(toolRun: toolRun, model: model)
            }
        }
        .padding(18)
        .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }
}

private struct ThinkingIndicatorCard: View {
    var body: some View {
        HStack(spacing: 12) {
            ProgressView()
                .controlSize(.small)
            VStack(alignment: .leading, spacing: 4) {
                Text("Skitter is working")
                    .font(.subheadline.weight(.semibold))
                Text("The current request is still running. Replies and approval requests will appear here as soon as they arrive.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(uiColor: .secondarySystemBackground))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(Color.accentColor.opacity(0.24), style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
                )
        )
    }
}

private struct MessageBubble: View {
    let message: ChatMessage
    let model: AppModel
    let settings: SettingsStore
    @ObservedObject var speaker: VoicePlaybackController
    let openURL: OpenURLAction
    @Environment(\.colorScheme) private var colorScheme

    private var isUser: Bool {
        message.role == .user
    }

    private var bubbleColor: Color {
        if isUser {
            return Color(uiColor: .secondarySystemBackground)
        }
        if colorScheme == .dark {
            return Color(red: 0.16, green: 0.23, blue: 0.32)
        }
        return Color(red: 0.89, green: 0.95, blue: 1.0)
    }

    private var bubbleStrokeColor: Color {
        if isUser {
            return Color.primary.opacity(colorScheme == .dark ? 0.12 : 0.06)
        }
        return Color.accentColor.opacity(colorScheme == .dark ? 0.28 : 0.14)
    }

    private var messageTextColor: Color {
        colorScheme == .dark ? .white : .primary
    }

    private var metadataTextColor: Color {
        if colorScheme == .dark {
            return .white.opacity(0.68)
        }
        return .secondary
    }

    var body: some View {
        HStack {
            if isUser {
                Spacer(minLength: 40)
            }

            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(message.role.title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(metadataTextColor)
                    Spacer()
                    Text(message.createdAt.formatted(date: .omitted, time: .shortened))
                        .font(.caption2)
                        .foregroundStyle(metadataTextColor)
                }

                MarkdownText(message.content.isEmpty ? "(empty)" : message.content)
                    .foregroundStyle(messageTextColor)

                if !message.attachments.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(message.attachments) { attachment in
                            AttachmentRow(attachment: attachment, resolvedURL: model.resolvedAttachmentURL(attachment), openURL: openURL)
                        }
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: 560, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(bubbleColor)
                    .overlay(
                        RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .stroke(bubbleStrokeColor, lineWidth: 1)
                    )
            )

            if !isUser {
                Spacer(minLength: 40)
            }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
        .contextMenu {
            Button("Copy Text") {
                copyToPasteboard(message.shareText)
            }
            if message.role != .user {
                Button("Speak Message") {
                    speaker.speak(
                        message.shareText,
                        preferredVoiceIdentifier: settings.effectiveSpeechSynthesisVoiceIdentifier,
                        preferredLanguageIdentifier: settings.defaultSpeechSynthesisLanguageIdentifier
                    )
                }
            }
        }
    }
}

private struct AttachmentRow: View {
    let attachment: MessageAttachment
    let resolvedURL: URL?
    let openURL: OpenURLAction
    @Environment(\.colorScheme) private var colorScheme

    private var attachmentBackground: Color {
        if colorScheme == .dark {
            return Color.black.opacity(0.18)
        }
        return Color.white.opacity(0.45)
    }

    private var primaryTextColor: Color {
        colorScheme == .dark ? .white : .primary
    }

    private var secondaryTextColor: Color {
        colorScheme == .dark ? .white.opacity(0.68) : .secondary
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "paperclip")
                .foregroundStyle(secondaryTextColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(attachment.filename)
                    .font(.caption.weight(.medium))
                    .lineLimit(1)
                    .foregroundStyle(primaryTextColor)
                Text(attachment.contentType)
                    .font(.caption2)
                    .foregroundStyle(secondaryTextColor)
            }
            Spacer()
            if let resolvedURL {
                Button("Open") {
                    openURL(resolvedURL)
                }
                .buttonStyle(.bordered)

                ShareLink(item: resolvedURL) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .labelStyle(.iconOnly)
            }
        }
        .padding(10)
        .background(attachmentBackground, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

private struct SessionDetailsSheet: View {
    @ObservedObject var model: AppModel

    var body: some View {
        NavigationStack {
            List {
                Section("Session") {
                    LabeledContent("Model", value: model.modelName)
                    LabeledContent("Context", value: "\(model.contextTokens)")
                    LabeledContent("Total tokens", value: "\(model.totalTokens)")
                    LabeledContent("Session cost", value: "$\(String(format: "%.2f", model.sessionCost))")
                }

                Section("Model Picker") {
                    if model.availableModels.isEmpty {
                        Text("No models available yet.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(model.availableModels, id: \.self) { modelName in
                            Button {
                                Task {
                                    await model.switchModel(to: modelName)
                                }
                            } label: {
                                HStack {
                                    Text(modelName)
                                    Spacer()
                                    if modelName == model.modelName {
                                        Image(systemName: "checkmark")
                                            .foregroundStyle(Color.accentColor)
                                    }
                                }
                            }
                        }
                    }
                }

                Section("Status") {
                    LabeledContent("Health", value: model.health.label)
                    LabeledContent("Activity", value: model.activity.label)
                }
            }
            .navigationTitle("Session Details")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

private struct ApprovalsScreen: View {
    @ObservedObject var model: AppModel

    var body: some View {
        List {
            if model.pendingApprovals.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "checkmark.shield")
                        .font(.system(size: 36))
                        .foregroundStyle(.green)
                    Text("No pending approvals")
                        .font(.headline)
                    Text("Tool approval requests will appear here when an agent needs confirmation.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 48)
            } else {
                ForEach(model.pendingApprovals) { toolRun in
                    ApprovalCard(toolRun: toolRun, model: model)
                        .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                        .listRowSeparator(.hidden)
                }
            }
        }
        .listStyle(.plain)
        .navigationTitle("Approvals")
    }
}

private struct ApprovalCard: View {
    let toolRun: ToolRunStatus
    @ObservedObject var model: AppModel
    @State private var showsParameters = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(toolRun.tool)
                        .font(.headline)
                    Text(approvalDetailLine)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusChip(label: toolRun.status.capitalized, tint: .orange)
            }

            if let requestedBy = toolRun.requestedBy, !requestedBy.isEmpty {
                Label(requestedBy, systemImage: "person.crop.circle.badge.checkmark")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if !toolRun.reasoning.isEmpty {
                Text(toolRun.reasoning.joined(separator: "\n"))
                    .font(.subheadline)
            }

            if !toolRun.secretRefs.isEmpty {
                Text("Secrets: \(toolRun.secretRefs.joined(separator: ", "))")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            DisclosureGroup("Parameters", isExpanded: $showsParameters) {
                ScrollView(.horizontal, showsIndicators: false) {
                    Text(toolRun.inputPrettyJSON())
                        .font(.caption.monospaced())
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                }
                .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .font(.subheadline.weight(.medium))

            HStack(spacing: 12) {
                Button("Approve") {
                    Task {
                        await model.approve(toolRun)
                    }
                }
                .buttonStyle(.borderedProminent)

                Button("Deny", role: .destructive) {
                    Task {
                        await model.deny(toolRun)
                    }
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(18)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private var approvalDetailLine: String {
        let who: String
        if let requestedBy = toolRun.requestedBy?.trimmingCharacters(in: .whitespacesAndNewlines), !requestedBy.isEmpty {
            who = " by \(requestedBy)"
        } else {
            who = ""
        }
        let relative = RelativeTimeFormatters.approvals.localizedString(for: toolRun.createdAt, relativeTo: Date())
        return "Requested\(who) \(relative)"
    }
}

private struct VoiceScreen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @ObservedObject var notifications: NotificationManager
    @StateObject private var speechController = SpeechCaptureController()
    @StateObject private var speaker = VoicePlaybackController()
    @State private var knownReplyID: String?
    @State private var didPrimeReplyID = false
    @State private var isSendingUtterance = false
    @State private var showsSpeechVoicePicker = false

    private var selectedVoiceModelLabel: String {
        let cleaned = settings.preferredVoiceModel.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "Session default" : cleaned
    }

    private var selectedRecognitionLanguageLabel: String {
        RecognitionLanguageOption.title(for: settings.speechRecognitionLocaleIdentifier)
    }

    private var selectedSpeechVoiceLabel: String {
        SpeechVoiceCatalog.title(
            for: settings.speechSynthesisVoiceIdentifier,
            preferredLanguageIdentifier: settings.defaultSpeechSynthesisLanguageIdentifier
        )
    }

    private var latestReplyText: String {
        let text = model.latestAssistantMessage?.content.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if text.isEmpty {
            return "Speak to send a message to the active session. Replies will appear here and can be spoken back automatically."
        }
        return text
    }

    private var statusLine: String {
        if speaker.isSpeaking {
            return "Speaking reply"
        }
        if isSendingUtterance || model.isSending {
            return "Waiting for Skitter..."
        }
        if speechController.isPreparing {
            return "Preparing microphone..."
        }
        if speechController.isListening {
            return "Listening..."
        }
        if !speechController.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Transcript ready"
        }
        if let error = speechController.errorText, !error.isEmpty {
            return error
        }
        return speechController.statusText
    }

    private var statusTint: Color {
        if speaker.isSpeaking {
            return Color(red: 0.23, green: 0.73, blue: 0.99)
        }
        if isSendingUtterance || model.isSending {
            return Color(red: 0.98, green: 0.70, blue: 0.24)
        }
        if speechController.isListening {
            return Color(red: 0.25, green: 0.78, blue: 0.56)
        }
        if speechController.isPreparing {
            return Color(red: 0.80, green: 0.54, blue: 0.98)
        }
        if speechController.errorText != nil {
            return .orange
        }
        return .white.opacity(0.76)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                voiceHero
                transcriptCard
                latestReplyCard
                voiceSettingsCard
            }
            .padding(20)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .background(
            LinearGradient(
                colors: [
                    Color(red: 0.07, green: 0.11, blue: 0.17),
                    Color(red: 0.07, green: 0.18, blue: 0.24),
                    Color(red: 0.12, green: 0.11, blue: 0.19),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()
        )
        .navigationTitle("Voice")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            speechController.setRecognitionLocaleIdentifier(settings.effectiveSpeechRecognitionLocaleIdentifier)
            if !didPrimeReplyID {
                knownReplyID = model.latestAssistantMessage?.id
                didPrimeReplyID = true
            }
        }
        .onDisappear {
            speechController.stopListening(clearTranscript: false)
            speaker.stop()
        }
        .onChange(of: model.latestAssistantMessage?.id) { _, newValue in
            handleAssistantReplyChange(newValue)
        }
        .onChange(of: settings.speechRecognitionLocaleIdentifier) { _, _ in
            speechController.setRecognitionLocaleIdentifier(settings.effectiveSpeechRecognitionLocaleIdentifier)
        }
        .sheet(isPresented: $showsSpeechVoicePicker) {
            SpeechVoicePickerSheet(settings: settings)
        }
    }

    private var voiceHero: some View {
        VStack(spacing: 18) {
            VoiceOrbView(
                audioLevel: speechController.audioLevel,
                isListening: speechController.isListening,
                isWaiting: isSendingUtterance || model.isSending || speechController.isPreparing,
                isSpeaking: speaker.isSpeaking
            )
            .frame(width: 266, height: 266)
            .padding(.top, 8)

            Text("Skitter Voice")
                .font(.title2.weight(.semibold))
                .foregroundStyle(.white)

            Text(statusLine)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(statusTint)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(.thinMaterial, in: Capsule())

            HStack(spacing: 12) {
                Button(mainVoiceButtonTitle) {
                    Task {
                        await toggleListening()
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(speechController.isListening ? .red.opacity(0.85) : statusTint.opacity(0.9))
                .disabled(isSendingUtterance || model.isSending)

                if !speechController.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Button("Send Now") {
                        speechController.submitCurrentTranscript()
                    }
                    .buttonStyle(.bordered)
                    .disabled(isSendingUtterance || model.isSending)
                }

                if speaker.isSpeaking {
                    Button("Stop Reply") {
                        speaker.stop()
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let error = speechController.errorText, !error.isEmpty {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(Color(red: 1.0, green: 0.72, blue: 0.72))
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 420)
            }
        }
        .padding(26)
        .frame(maxWidth: .infinity)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 32, style: .continuous))
    }

    private var transcriptCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Live Transcript", systemImage: "captions.bubble")
                .font(.headline)
                .foregroundStyle(.white)

            Text(
                speechController.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "Your transcript will appear here as you speak."
                    : speechController.transcript
            )
            .font(.body)
            .foregroundStyle(.white.opacity(0.88))
            .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 12) {
                Label("Silence send", systemImage: "timer")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.74))
                Spacer()
                Text("\(settings.conversationSilenceSeconds, specifier: "%.1f")s")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white.opacity(0.84))
            }
        }
        .padding(22)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private var latestReplyCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Latest Assistant Reply", systemImage: "text.bubble")
                .font(.headline)
                .foregroundStyle(.white)

            Text(latestReplyText)
                .font(.body)
                .foregroundStyle(.white.opacity(0.86))

            HStack(spacing: 12) {
                Button(speaker.isSpeaking ? "Stop Playback" : "Speak Reply") {
                    if speaker.isSpeaking {
                        speaker.stop()
                    } else if let text = model.latestAssistantMessage?.shareText,
                              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        speaker.speak(
                            text,
                            preferredVoiceIdentifier: settings.effectiveSpeechSynthesisVoiceIdentifier,
                            preferredLanguageIdentifier: settings.defaultSpeechSynthesisLanguageIdentifier
                        )
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.latestAssistantMessage == nil)

                ShareLink(item: model.latestAssistantMessage?.shareText ?? latestReplyText, subject: Text("Skitter reply")) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(.bordered)

                Button("Open Chat") {
                    model.selectedSection = .chat
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(22)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private var voiceSettingsCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Voice Preferences", systemImage: "slider.horizontal.3")
                .font(.headline)
                .foregroundStyle(.white)

            Toggle("Speak replies automatically when possible", isOn: $settings.speaksReplies)
                .tint(.teal)
                .foregroundStyle(.white)

            Stepper(
                value: $settings.conversationSilenceSeconds,
                in: 0.6...5.0,
                step: 0.1
            ) {
                Text("Silence threshold: \(settings.conversationSilenceSeconds, specifier: "%.1f")s")
                    .foregroundStyle(.white.opacity(0.84))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Reply voice")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)

                Button {
                    showsSpeechVoicePicker = true
                } label: {
                    HStack {
                        Text(selectedSpeechVoiceLabel)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption.weight(.semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(.plain)

                Text("Siri voices are not exposed to third-party text-to-speech on iOS. Automatic prefers the best installed system voice for your device language.")
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.68))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Recognition language")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)

                Menu {
                    Button {
                        settings.speechRecognitionLocaleIdentifier = ""
                    } label: {
                        if settings.speechRecognitionLocaleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Label("System Default (\(RecognitionLanguageOption.currentLocaleDescription))", systemImage: "checkmark")
                        } else {
                            Text("System Default (\(RecognitionLanguageOption.currentLocaleDescription))")
                        }
                    }

                    if !RecognitionLanguageOption.available.isEmpty {
                        Divider()
                        ForEach(RecognitionLanguageOption.available) { option in
                            Button {
                                settings.speechRecognitionLocaleIdentifier = option.id
                            } label: {
                                if option.id == settings.speechRecognitionLocaleIdentifier {
                                    Label(option.title, systemImage: "checkmark")
                                } else {
                                    Text(option.title)
                                }
                            }
                        }
                    }
                } label: {
                    HStack {
                        Text(selectedRecognitionLanguageLabel)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption.weight(.semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(.plain)

                Text("Used by both the chat microphone and dedicated voice mode.")
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.68))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Voice model")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                Menu {
                    Button {
                        settings.preferredVoiceModel = ""
                    } label: {
                        if settings.preferredVoiceModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Label("Session default", systemImage: "checkmark")
                        } else {
                            Text("Session default")
                        }
                    }

                    if !model.availableModels.isEmpty {
                        Divider()
                        ForEach(model.availableModels, id: \.self) { modelName in
                            Button {
                                settings.preferredVoiceModel = modelName
                            } label: {
                                if modelName == settings.preferredVoiceModel {
                                    Label(modelName, systemImage: "checkmark")
                                } else {
                                    Text(modelName)
                                }
                            }
                        }
                    }
                } label: {
                    HStack {
                        Text(selectedVoiceModelLabel)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption.weight(.semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(.plain)

                Text("Applies only to the dedicated voice mode. Leave it on session default to mirror chat.")
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.68))
            }

            if notifications.authorizationStatus != .authorized {
                Text("Notifications are currently \(notifications.authorizationLabel.lowercased()). Enabling them keeps voice replies visible when the app is not active.")
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.68))
            }
        }
        .padding(22)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private var mainVoiceButtonTitle: String {
        if speechController.isListening || speechController.isPreparing {
            return "Stop"
        }
        return "Start"
    }

    private func toggleListening() async {
        if speechController.isListening || speechController.isPreparing {
            speechController.stopListening(clearTranscript: false)
            return
        }

        speaker.stop()
        await speechController.startListening(
            silenceInterval: settings.conversationSilenceSeconds,
            autoSubmitOnSilence: true,
            onTranscript: { _ in },
            onSegment: { transcript in
                await sendVoiceUtterance(transcript)
            }
        )
    }

    private func sendVoiceUtterance(_ transcript: String) async {
        let cleaned = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }

        isSendingUtterance = true
        defer {
            isSendingUtterance = false
        }

        let modelOverride = settings.preferredVoiceModel.trimmingCharacters(in: .whitespacesAndNewlines)
        await model.send(
            text: cleaned,
            modelNameOverride: modelOverride.isEmpty ? nil : modelOverride
        )
    }

    private func handleAssistantReplyChange(_ newValue: String?) {
        guard didPrimeReplyID else {
            knownReplyID = newValue
            didPrimeReplyID = true
            return
        }

        guard newValue != knownReplyID else { return }
        knownReplyID = newValue

        guard settings.speaksReplies else { return }
        guard let reply = model.latestAssistantMessage?.shareText,
              !reply.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        speaker.speak(
            reply,
            preferredVoiceIdentifier: settings.effectiveSpeechSynthesisVoiceIdentifier,
            preferredLanguageIdentifier: settings.defaultSpeechSynthesisLanguageIdentifier
        )
    }
}

private struct VoiceOrbView: View {
    let audioLevel: Double
    let isListening: Bool
    let isWaiting: Bool
    let isSpeaking: Bool

    @State private var breathe = false
    @State private var rotate = false

    private var ringTint: Color {
        if isSpeaking {
            return Color(red: 0.24, green: 0.79, blue: 1.0)
        }
        if isWaiting {
            return Color(red: 0.97, green: 0.73, blue: 0.35)
        }
        if isListening {
            return Color(red: 0.32, green: 0.91, blue: 0.63)
        }
        return .white.opacity(0.55)
    }

    private var coreScale: CGFloat {
        if isSpeaking {
            return 1 + CGFloat(0.08 + (audioLevel * 0.16))
        }
        if isListening {
            return 1 + CGFloat(0.03 + (audioLevel * 0.12))
        }
        if isWaiting {
            return breathe ? 1.03 : 0.99
        }
        return breathe ? 1.01 : 0.98
    }

    private var iconName: String {
        if isSpeaking {
            return "speaker.wave.3.fill"
        }
        if isWaiting {
            return "ellipsis"
        }
        if isListening {
            return "waveform"
        }
        return "mic.fill"
    }

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .stroke(ringTint.opacity(0.18 - (Double(index) * 0.03)), lineWidth: 1.2)
                    .scaleEffect(ringScale(index))
                    .blur(radius: CGFloat(index) * 1.2)
            }

            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            ringTint.opacity(0.92),
                            ringTint.opacity(0.45),
                            Color(red: 0.06, green: 0.09, blue: 0.14).opacity(0.0),
                        ],
                        center: .center,
                        startRadius: 12,
                        endRadius: 170
                    )
                )
                .scaleEffect(coreScale)
                .shadow(color: ringTint.opacity(0.34), radius: 24, x: 0, y: 14)

            Circle()
                .fill(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.24),
                            Color.white.opacity(0.08),
                            Color.black.opacity(0.10),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .padding(36)

            Image(systemName: iconName)
                .font(.system(size: 56, weight: .medium))
                .foregroundStyle(.white)
                .rotationEffect(.degrees(isWaiting ? (rotate ? 7 : -7) : 0))
        }
        .padding(14)
        .onAppear {
            withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) {
                breathe.toggle()
            }
            withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
                rotate.toggle()
            }
        }
    }

    private func ringScale(_ index: Int) -> CGFloat {
        let base = 0.74 + CGFloat(index) * 0.14
        if isSpeaking || isListening {
            return base + CGFloat(audioLevel) * (0.1 + CGFloat(index) * 0.04)
        }
        if isWaiting {
            return base + (breathe ? 0.04 : -0.02)
        }
        return base + (breathe ? 0.02 : 0)
    }
}

private struct SettingsScreen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @ObservedObject var notifications: NotificationManager
    @State private var showsSpeechVoicePicker = false

    private var selectedVoiceModelLabel: String {
        let cleaned = settings.preferredVoiceModel.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "Session default" : cleaned
    }

    private var selectedRecognitionLanguageLabel: String {
        RecognitionLanguageOption.title(for: settings.speechRecognitionLocaleIdentifier)
    }

    private var selectedSpeechVoiceLabel: String {
        SpeechVoiceCatalog.title(
            for: settings.speechSynthesisVoiceIdentifier,
            preferredLanguageIdentifier: settings.defaultSpeechSynthesisLanguageIdentifier
        )
    }

    var body: some View {
        Form {
            Section("Server") {
                TextField("API URL", text: $settings.apiURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()

                Button("Test Connection") {
                    Task {
                        _ = await model.testServerConnection()
                    }
                }
            }

            Section("Account") {
                if let user = model.currentUser {
                    LabeledContent("Display name", value: user.displayName)
                    LabeledContent("User ID", value: user.id)
                }
                Button("Refresh Session") {
                    Task {
                        await model.refreshState(showErrors: true)
                    }
                }
                Button("Log Out", role: .destructive) {
                    Task {
                        await model.logout()
                    }
                }
            }

            Section("Notifications") {
                LabeledContent("Permission", value: notifications.authorizationLabel)
                if !notifications.deviceTokenHex.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("APNs token")
                        Text(notifications.deviceTokenHex)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .foregroundStyle(.secondary)
                    }
                }
                if !notifications.registrationStatusText.isEmpty {
                    Text(notifications.registrationStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Button("Enable Notifications") {
                    Task {
                        await model.requestNotifications()
                    }
                }
            }

            Section("Voice") {
                Toggle("Speak replies", isOn: $settings.speaksReplies)
                Stepper(
                    value: $settings.conversationSilenceSeconds,
                    in: 0.6...5.0,
                    step: 0.1
                ) {
                    Text("Silence threshold: \(settings.conversationSilenceSeconds, specifier: "%.1f")s")
                }

                Button {
                    showsSpeechVoicePicker = true
                } label: {
                    LabeledContent("Reply voice", value: selectedSpeechVoiceLabel)
                }
                .buttonStyle(.plain)

                Menu {
                    Button {
                        settings.preferredVoiceModel = ""
                    } label: {
                        if settings.preferredVoiceModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Label("Session default", systemImage: "checkmark")
                        } else {
                            Text("Session default")
                        }
                    }

                    if !model.availableModels.isEmpty {
                        Divider()
                        ForEach(model.availableModels, id: \.self) { modelName in
                            Button {
                                settings.preferredVoiceModel = modelName
                            } label: {
                                if modelName == settings.preferredVoiceModel {
                                    Label(modelName, systemImage: "checkmark")
                                } else {
                                    Text(modelName)
                                }
                            }
                        }
                    }
                } label: {
                    LabeledContent("Voice model", value: selectedVoiceModelLabel)
                }

                Menu {
                    Button {
                        settings.speechRecognitionLocaleIdentifier = ""
                    } label: {
                        if settings.speechRecognitionLocaleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Label("System Default (\(RecognitionLanguageOption.currentLocaleDescription))", systemImage: "checkmark")
                        } else {
                            Text("System Default (\(RecognitionLanguageOption.currentLocaleDescription))")
                        }
                    }

                    if !RecognitionLanguageOption.available.isEmpty {
                        Divider()
                        ForEach(RecognitionLanguageOption.available) { option in
                            Button {
                                settings.speechRecognitionLocaleIdentifier = option.id
                            } label: {
                                if option.id == settings.speechRecognitionLocaleIdentifier {
                                    Label(option.title, systemImage: "checkmark")
                                } else {
                                    Text(option.title)
                                }
                            }
                        }
                    }
                } label: {
                    LabeledContent("Recognition language", value: selectedRecognitionLanguageLabel)
                }

                Text("Siri voices are not available to third-party text-to-speech on iOS. Automatic uses the best installed system voice for your device language.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("About") {
                LabeledContent("Build", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1")
                Text("Remote push delivery still needs a backend device-registration endpoint. This app already supports permission flow, badges, APNs token capture, and local notification fallback.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Settings")
        .sheet(isPresented: $showsSpeechVoicePicker) {
            SpeechVoicePickerSheet(settings: settings)
        }
    }
}

private struct SpeechVoicePickerSheet: View {
    @ObservedObject var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss

    private var automaticTitle: String {
        SpeechVoiceCatalog.automaticTitle(for: settings.defaultSpeechSynthesisLanguageIdentifier)
    }

    private var speechVoiceOptions: [SpeechVoiceOption] {
        SpeechVoiceCatalog.availableOptions(for: settings.defaultSpeechSynthesisLanguageIdentifier)
    }

    var body: some View {
        NavigationStack {
            List {
                Section("Automatic") {
                    Button {
                        settings.speechSynthesisVoiceIdentifier = ""
                        dismiss()
                    } label: {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Automatic")
                                    .foregroundStyle(.primary)
                                Text(automaticTitle.replacingOccurrences(of: "Automatic ", with: ""))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if settings.speechSynthesisVoiceIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(Color.accentColor)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                }

                Section("Installed Voices") {
                    ForEach(speechVoiceOptions) { option in
                        Button {
                            settings.speechSynthesisVoiceIdentifier = option.id
                            dismiss()
                        } label: {
                            HStack(spacing: 12) {
                                Text(option.title)
                                    .foregroundStyle(.primary)
                                Spacer()
                                if option.id == settings.speechSynthesisVoiceIdentifier {
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(Color.accentColor)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .navigationTitle("Reply Voice")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}

private struct StatusChip: View {
    let label: String
    let tint: Color

    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(tint.opacity(0.12), in: Capsule())
            .foregroundStyle(tint)
    }
}

private struct MarkdownText: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        if let attributed = try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            Text(attributed)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Text(text)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private func copyToPasteboard(_ text: String) {
    UIPasteboard.general.string = text
}
