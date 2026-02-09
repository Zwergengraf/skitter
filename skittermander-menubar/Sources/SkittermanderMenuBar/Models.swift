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
    let createdAt: String
}
