import SwiftUI

struct ChatView: View {
    @ObservedObject var state: AppState

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

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(state.messages) { message in
                            messageRow(message)
                        }
                    }
                    .padding(12)
                }
                .onChange(of: state.messages.count) { _, _ in
                    if let lastID = state.messages.last?.id {
                        proxy.scrollTo(lastID, anchor: .bottom)
                    }
                }
            }

            Divider()

            HStack(spacing: 8) {
                TextField("Message", text: $state.draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
                    .onSubmit {
                        Task { await state.sendCurrentDraft() }
                    }
                Button(action: {
                    Task { await state.sendCurrentDraft() }
                }) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                }
                .buttonStyle(.plain)
                .disabled(state.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(12)
        }
        .frame(minWidth: 380, minHeight: 420)
        .background(.ultraThinMaterial)
        .preferredColorScheme(.light)
        .task {
            do {
                _ = try await state.ensureSession(forceNew: false)
            } catch {
                // Status strip already shows health errors.
            }
        }
    }

    @ViewBuilder
    private func messageRow(_ message: ChatMessage) -> some View {
        let isUser = message.role == .user
        VStack(alignment: .leading, spacing: 6) {
            Text(label(for: message.role))
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(message.content.isEmpty ? "(empty)" : message.content)
                .font(.body)
            if !message.attachments.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(message.attachments) { attachment in
                        HStack(spacing: 6) {
                            Image(systemName: "paperclip")
                                .font(.caption)
                            Text(attachment.filename)
                                .font(.caption)
                                .lineLimit(1)
                            Spacer()
                        }
                    }
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(isUser ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.12))
        )
        .id(message.id)
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
}
