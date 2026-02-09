import AppKit
import SwiftUI

struct ChatView: View {
    @ObservedObject var state: AppState
    @State private var visibleLimit: Int = 160

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

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(state.health.label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(state.activity.label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)

            Divider()

            HStack(spacing: 10) {
                Text(
                    "Model: \(state.modelName)  |  Tokens: \(state.totalTokens)  |  Context: \(state.contextTokens)  |  Cost: $\(String(format: "%.2f", state.sessionCost))"
                )
                .lineLimit(1)
                .truncationMode(.middle)
                .minimumScaleFactor(0.85)
                Spacer()
            }
            .font(.caption.monospaced())
            .padding(.horizontal, 12)
            .padding(.vertical, 6)

            if let banner = state.errorBanner {
                Divider()
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
                .background(Color.red.opacity(0.08))
            }

            if !state.progressStatusText.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(state.progressStatusText.split(separator: "\n"), id: \.self) { line in
                        Text(String(line))
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color.secondary.opacity(0.08))
            }

            Divider()

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if hiddenCount > 0 {
                            Button("Load \(min(150, hiddenCount)) older messages (\(hiddenCount) remaining)") {
                                visibleLimit += 150
                            }
                            .buttonStyle(.bordered)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.bottom, 6)
                        }
                        ForEach(displayedMessages) { message in
                            messageRow(message)
                        }
                    }
                    .padding(12)
                }
                .onChange(of: state.messages.count) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: state.chatOpenSignal) { _, _ in
                    scrollToBottom(proxy)
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
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.secondary.opacity(0.08)))
                }

                HStack(alignment: .bottom, spacing: 8) {
                    CommandInputTextView(
                        text: $state.draft,
                        onSubmit: { Task { await state.sendCurrentDraft() } },
                        onEscape: {
                            state.draft = ""
                        }
                    )
                    .frame(minHeight: 54, idealHeight: 96, maxHeight: 130)

                    Button(action: {
                        Task { await state.sendCurrentDraft() }
                    }) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title2)
                    }
                    .buttonStyle(.plain)
                    .disabled(state.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                HStack {
                    Text("Enter: send | Cmd+Enter: newline")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
            }
            .padding(12)
        }
        .frame(
            minWidth: 500,
            minHeight: 620
        )
        .background(.ultraThinMaterial)
        .preferredColorScheme(.light)
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
    private func messageRow(_ message: ChatMessage) -> some View {
        let isUser = message.role == .user
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label(for: message.role))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if message.role == .assistant {
                    Button {
                        copyToPasteboard(message.content)
                    } label: {
                        Label("Copy", systemImage: "doc.on.doc")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.borderless)
                    .font(.caption)

                    Button {
                        copyToPasteboard(markdownForMessage(message))
                    } label: {
                        Label("Copy MD", systemImage: "doc.text")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.borderless)
                    .font(.caption)
                }
            }

            Text(message.content.isEmpty ? "(empty)" : message.content)
                .font(.body)
                .textSelection(.enabled)

            if !message.attachments.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(message.attachments.enumerated()), id: \.offset) { idx, attachment in
                        attachmentView(attachment)
                    }
                }
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(isUser ? Color.accentColor.opacity(0.10) : Color.secondary.opacity(0.10))
        )
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
                        NSWorkspace.shared.open(url)
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                    Button("Download") {
                        Task { await downloadAttachment(url: url, preferredName: attachment.filename) }
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                }
            }
            if let url, isImageAttachment(attachment) {
                AsyncImage(url: url) { image in
                    image
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 320)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                } placeholder: {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.secondary.opacity(0.15))
                        .frame(width: 320, height: 120)
                        .overlay(ProgressView())
                }
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.secondary.opacity(0.08)))
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        guard let lastID = state.messages.last?.id else { return }
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo(lastID, anchor: .bottom)
            }
        }
    }

    private func label(for role: ChatRole) -> String {
        switch role {
        case .user:
            return "You"
        case .assistant:
            return "Skittermander"
        case .system:
            return "System"
        case .other:
            return "Message"
        }
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

    private func downloadAttachment(url: URL, preferredName: String) async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let downloadsDir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
                ?? FileManager.default.temporaryDirectory
            var destination = downloadsDir.appendingPathComponent(preferredName)
            if FileManager.default.fileExists(atPath: destination.path) {
                let ext = destination.pathExtension
                let stem = destination.deletingPathExtension().lastPathComponent
                let stamped = "\(stem)-\(Int(Date().timeIntervalSince1970))"
                destination = downloadsDir.appendingPathComponent(stamped).appendingPathExtension(ext)
            }
            try data.write(to: destination)
            NSWorkspace.shared.activateFileViewerSelecting([destination])
        } catch {
            state.errorBanner = "Download failed: \(error.localizedDescription)"
        }
    }
}
