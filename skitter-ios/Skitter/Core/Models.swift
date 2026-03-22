import Foundation

enum AuthenticationState: Equatable {
    case loading
    case signedOut
    case signedIn
}

enum HealthState: Equatable {
    case checking
    case healthy
    case error(String)

    var label: String {
        switch self {
        case .checking:
            return "Checking"
        case .healthy:
            return "Healthy"
        case let .error(message):
            return "Error: \(message)"
        }
    }
}

enum ActivityState: Equatable {
    case idle
    case thinking
    case activeTasks(Int)

    var label: String {
        switch self {
        case .idle:
            return "Idle"
        case .thinking:
            return "Thinking"
        case let .activeTasks(count):
            return count == 1 ? "1 approval" : "\(count) approvals"
        }
    }
}

enum ChatRole: String {
    case user
    case assistant
    case system
    case other

    var title: String {
        switch self {
        case .user:
            return "You"
        case .assistant:
            return "Skitter"
        case .system:
            return "System"
        case .other:
            return "Other"
        }
    }
}

enum AppSection: String, CaseIterable, Identifiable {
    case chat
    case voice
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .chat:
            return "Chat"
        case .voice:
            return "Voice"
        case .settings:
            return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .chat:
            return "bubble.left.and.bubble.right"
        case .voice:
            return "waveform"
        case .settings:
            return "gearshape"
        }
    }
}

struct LocalCommand: Identifiable, Hashable {
    let id: String
    let name: String
    let usage: String
    let description: String

    static let all: [LocalCommand] = [
        LocalCommand(id: "help", name: "/help", usage: "/help", description: "Show available commands"),
        LocalCommand(id: "new", name: "/new", usage: "/new", description: "Start a new session"),
        LocalCommand(id: "memory_reindex", name: "/memory_reindex", usage: "/memory_reindex", description: "Rebuild memory embeddings"),
        LocalCommand(id: "memory_search", name: "/memory_search", usage: "/memory_search <query>", description: "Search semantic memory"),
        LocalCommand(id: "schedule_list", name: "/schedule_list", usage: "/schedule_list", description: "List scheduled jobs"),
        LocalCommand(id: "schedule_delete", name: "/schedule_delete", usage: "/schedule_delete <job_id>", description: "Delete a scheduled job"),
        LocalCommand(id: "schedule_pause", name: "/schedule_pause", usage: "/schedule_pause <job_id>", description: "Pause a scheduled job"),
        LocalCommand(id: "schedule_resume", name: "/schedule_resume", usage: "/schedule_resume <job_id>", description: "Resume a scheduled job"),
        LocalCommand(id: "tools", name: "/tools", usage: "/tools", description: "Show tool approval settings"),
        LocalCommand(id: "model", name: "/model", usage: "/model [provider/model]", description: "List or set the active model"),
        LocalCommand(id: "machine", name: "/machine", usage: "/machine [name_or_id]", description: "List or set the default machine"),
        LocalCommand(id: "pair", name: "/pair", usage: "/pair", description: "Create a pair code"),
        LocalCommand(id: "info", name: "/info", usage: "/info", description: "Show session usage info"),
    ]
}

enum CommandMatcher {
    static func filter(_ input: String, commands: [LocalCommand] = LocalCommand.all) -> [LocalCommand] {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard trimmed.hasPrefix("/") else { return [] }
        if trimmed == "/" {
            return commands
        }
        return commands.filter {
            $0.name.lowercased().hasPrefix(trimmed) || $0.usage.lowercased().hasPrefix(trimmed)
        }
    }
}

indirect enum JSONValue: Equatable, Decodable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
            return
        }
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
            return
        }
        if let value = try? container.decode(Double.self) {
            self = .number(value)
            return
        }
        if let value = try? container.decode(String.self) {
            self = .string(value)
            return
        }
        if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
            return
        }
        if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
            return
        }
        throw DecodingError.typeMismatch(
            JSONValue.self,
            DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Unsupported JSON value")
        )
    }

    func toAny() -> Any {
        switch self {
        case let .string(value):
            return value
        case let .number(value):
            return value
        case let .bool(value):
            return value
        case let .object(value):
            return value.mapValues { $0.toAny() }
        case let .array(value):
            return value.map { $0.toAny() }
        case .null:
            return NSNull()
        }
    }

    var stringValue: String? {
        if case let .string(value) = self {
            return value
        }
        return nil
    }
}

struct APIConfiguration {
    let baseURL: String
    let token: String
}

struct MessageAttachment: Identifiable, Equatable, Hashable {
    let filename: String
    let contentType: String
    let downloadURL: String?
    let sourceURL: String?

    var id: String {
        "\(filename)|\(contentType)|\(downloadURL ?? "")|\(sourceURL ?? "")"
    }

    var preferredURLString: String? {
        let candidates = [downloadURL, sourceURL]
        for candidate in candidates {
            let cleaned = candidate?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if !cleaned.isEmpty {
                return cleaned
            }
        }
        return nil
    }

    var isImage: Bool {
        if contentType.lowercased().hasPrefix("image/") {
            return true
        }
        let lower = filename.lowercased()
        return lower.hasSuffix(".png")
            || lower.hasSuffix(".jpg")
            || lower.hasSuffix(".jpeg")
            || lower.hasSuffix(".gif")
            || lower.hasSuffix(".webp")
            || lower.hasSuffix(".heic")
    }
}

struct PendingComposerAttachment: Identifiable, Equatable {
    let id: String
    let filename: String
    let contentType: String
    let data: Data
}

struct ChatMessage: Identifiable, Equatable, Hashable {
    let id: String
    let role: ChatRole
    let content: String
    let createdAt: Date
    let attachments: [MessageAttachment]

    static func local(id: String = "local-\(UUID().uuidString)", role: ChatRole, content: String) -> ChatMessage {
        ChatMessage(id: id, role: role, content: content, createdAt: Date(), attachments: [])
    }

    var markdownRepresentation: String {
        var lines = ["**\(role.title)**", "", content.isEmpty ? "(empty)" : content]
        if !attachments.isEmpty {
            lines.append("")
            for attachment in attachments {
                if let url = attachment.preferredURLString {
                    if attachment.isImage {
                        lines.append("![\(attachment.filename)](\(url))")
                    } else {
                        lines.append("[\(attachment.filename)](\(url))")
                    }
                } else {
                    lines.append("- \(attachment.filename) (\(attachment.contentType))")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    var shareText: String {
        content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "(empty)" : content
    }
}

struct SessionSnapshot {
    let id: String
    let contextTokens: Int
    let totalTokens: Int
    let totalCost: Double
    let modelName: String
}

struct AuthUser: Equatable {
    let id: String
    let displayName: String
    let approved: Bool
}

struct ToolRunStatus: Identifiable, Equatable {
    let id: String
    let sessionID: String
    let tool: String
    let status: String
    let createdAt: Date
    let requestedBy: String?
    let input: [String: JSONValue]
    let reasoning: [String]

    func inputPrettyJSON(maxChars: Int = 3000) -> String {
        guard !input.isEmpty else {
            return "{}"
        }
        do {
            let object = input.mapValues { $0.toAny() }
            let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
            var text = String(decoding: data, as: UTF8.self)
            if text.count > maxChars {
                text = String(text.prefix(maxChars)) + "\n..."
            }
            return text
        } catch {
            return String(describing: input)
        }
    }

    var secretRefs: [String] {
        guard let refs = input["secret_refs"] else { return [] }
        guard case let .array(values) = refs else { return [] }
        return values.compactMap(\.stringValue)
    }
}

struct PendingUserPrompt: Identifiable, Equatable {
    let id: String
    let sessionID: String
    let question: String
    let choices: [String]
    let allowFreeText: Bool
    let status: String
    let createdAt: Date
}

struct CommandResult {
    let ok: Bool
    let message: String
    let data: [String: JSONValue]?
}

struct HealthPayload: Decodable {
    let status: String
}

struct SessionPayload: Decodable {
    let id: String
    let model: String?
    let total_tokens: Int?
    let total_cost: Double?
    let last_input_tokens: Int?
    let last_model: String?
}

struct MessageMetaAttachmentPayload: Decodable {
    let filename: String
    let content_type: String
    let url: String?
    let download_url: String?
}

struct SessionMessagePayload: Decodable {
    let id: String
    let role: String
    let content: String
    let created_at: String
    let meta: [String: JSONValue]
}

struct SessionDetailPayload: Decodable {
    let messages: [SessionMessagePayload]
}

struct MessageAttachmentPayload: Decodable {
    let filename: String
    let content_type: String
    let url: String?
    let download_url: String?
}

struct MessagePayload: Decodable {
    let id: String
    let role: String
    let content: String
    let created_at: String
    let attachments: [MessageAttachmentPayload]
}

struct AuthUserPayload: Decodable {
    let id: String
    let display_name: String
    let approved: Bool

    func toDomain() -> AuthUser {
        AuthUser(id: id, displayName: display_name, approved: approved)
    }
}

struct AuthTokenPayload: Decodable {
    let token: String
    let user: AuthUserPayload
}

struct ModelPayload: Decodable {
    let name: String
}

struct ToolRunPayload: Decodable {
    let id: String
    let tool: String
    let status: String
    let created_at: String
    let requested_by: String
    let session_id: String
    let input: [String: JSONValue]?
    let reasoning: [String]
}

struct UserPromptPayload: Decodable {
    let id: String
    let session_id: String
    let question: String
    let choices: [String]
    let allow_free_text: Bool
    let status: String
    let created_at: String
}

struct CommandExecutePayload: Decodable {
    let ok: Bool
    let message: String
    let data: [String: JSONValue]?
}
