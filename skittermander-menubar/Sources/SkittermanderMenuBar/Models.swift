import Foundation

enum HealthState: Equatable {
    case checking
    case healthy
    case error(String)

    var label: String {
        switch self {
        case .checking:
            return "checking"
        case .healthy:
            return "healthy"
        case let .error(message):
            return "error: \(message)"
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
            return "idle"
        case .thinking:
            return "thinking"
        case let .activeTasks(count):
            return "active tasks (\(count))"
        }
    }
}

enum ChatRole: String {
    case user
    case assistant
    case system
    case other
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
            var mapped: [String: Any] = [:]
            for (key, item) in value {
                mapped[key] = item.toAny()
            }
            return mapped
        case let .array(values):
            return values.map { $0.toAny() }
        case .null:
            return NSNull()
        }
    }
}

struct MessageAttachment: Identifiable {
    let id = UUID()
    let filename: String
    let contentType: String
    let downloadURL: String?
    let sourceURL: String?
}

struct ChatMessage: Identifiable {
    let id: String
    let role: ChatRole
    let content: String
    let createdAt: Date
    let attachments: [MessageAttachment]
}

struct SessionSnapshot {
    let id: String
    let contextTokens: Int
    let totalTokens: Int
    let totalCost: Double
    let modelName: String
}

struct ToolRunStatus {
    let id: String
    let sessionID: String
    let tool: String
    let status: String
    let createdAt: Date
    let requestedBy: String?
    let input: [String: JSONValue]

    func inputPrettyJSON(maxChars: Int = 3000) -> String {
        guard !input.isEmpty else {
            return "{}"
        }
        do {
            let object = input.mapValues { $0.toAny() }
            let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
            var text = String(decoding: data, as: UTF8.self)
            if text.count > maxChars {
                text = String(text.prefix(maxChars)) + "\n…"
            }
            return text
        } catch {
            return String(describing: input)
        }
    }

    var secretRefs: [String] {
        guard let refs = input["secret_refs"] else { return [] }
        guard case let .array(values) = refs else { return [] }
        return values.compactMap {
            if case let .string(text) = $0 {
                return text
            }
            return nil
        }
    }
}
