import Foundation
import UIKit

struct APIClient {
    enum APIError: LocalizedError {
        case invalidBaseURL
        case missingAuthToken
        case http(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .invalidBaseURL:
                return "Invalid API URL."
            case .missingAuthToken:
                return "Access token is required."
            case let .http(code, message):
                return "HTTP \(code): \(message)"
            case let .decoding(message):
                return "Decoding error: \(message)"
            }
        }
    }

    private let session: URLSession
    private static let isoFormatterWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.default
            configuration.timeoutIntervalForRequest = 120
            configuration.timeoutIntervalForResource = 900
            configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
            self.session = URLSession(configuration: configuration)
        }
    }

    func health(baseURL: String) async throws -> Bool {
        let request = try buildRequest(baseURL: baseURL, path: "/health", method: "GET", token: nil)
        let (data, response) = try await session.data(for: request)
        try ensureSuccess(response: response, data: data)
        let payload = try decode(HealthPayload.self, from: data)
        return payload.status.lowercased() == "ok"
    }

    func bootstrap(
        baseURL: String,
        bootstrapCode: String,
        displayName: String,
        deviceName: String? = nil,
        deviceType: String = "ios"
    ) async throws -> (token: String, user: AuthUser) {
        let body = [
            "bootstrap_code": bootstrapCode,
            "display_name": displayName,
            "device_name": deviceName ?? "",
            "device_type": deviceType,
        ]
        let payload: AuthTokenPayload = try await requestJSON(
            baseURL: baseURL,
            token: nil,
            path: "/v1/auth/bootstrap",
            method: "POST",
            body: body
        )
        return (payload.token, payload.user.toDomain())
    }

    func pair(
        baseURL: String,
        pairCode: String,
        deviceName: String? = nil,
        deviceType: String = "ios"
    ) async throws -> (token: String, user: AuthUser) {
        let body = [
            "pair_code": pairCode,
            "device_name": deviceName ?? "",
            "device_type": deviceType,
        ]
        let payload: AuthTokenPayload = try await requestJSON(
            baseURL: baseURL,
            token: nil,
            path: "/v1/auth/pair/complete",
            method: "POST",
            body: body
        )
        return (payload.token, payload.user.toDomain())
    }

    func authMe(config: APIConfiguration) async throws -> AuthUser {
        let payload: AuthUserPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/auth/me",
            method: "GET",
            body: Optional<Int>.none
        )
        return payload.toDomain()
    }

    func createOrResumeSession(
        config: APIConfiguration,
        reuseActive: Bool,
        origin: String = "ios"
    ) async throws -> String {
        let body: [String: AnyEncodable] = [
            "origin": AnyEncodable(origin),
            "reuse_active": AnyEncodable(reuseActive),
        ]
        let payload: SessionPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/sessions",
            method: "POST",
            body: body
        )
        return payload.id
    }

    func sessionSnapshot(config: APIConfiguration, sessionID: String) async throws -> SessionSnapshot {
        let payload: SessionPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/sessions/\(sessionID)",
            method: "GET",
            body: Optional<Int>.none
        )
        return SessionSnapshot(
            id: payload.id,
            contextTokens: payload.last_input_tokens ?? 0,
            totalTokens: payload.total_tokens ?? 0,
            totalCost: payload.total_cost ?? 0,
            modelName: payload.last_model ?? payload.model ?? "default"
        )
    }

    func sessionDetail(config: APIConfiguration, sessionID: String) async throws -> [ChatMessage] {
        let payload: SessionDetailPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/sessions/\(sessionID)/detail",
            method: "GET",
            body: Optional<Int>.none
        )
        return payload.messages.map { item in
            let role = ChatRole(rawValue: item.role.lowercased()) ?? .other
            let attachments = attachmentsFromMeta(item.meta, messageID: item.id)
            return ChatMessage(
                id: item.id,
                role: role,
                content: item.content,
                createdAt: parseDate(item.created_at),
                attachments: attachments
            )
        }
    }

    func sendMessage(
        config: APIConfiguration,
        sessionID: String,
        text: String,
        modelNameOverride: String? = nil,
        origin: String = "ios"
    ) async throws -> ChatMessage {
        var metadata: [String: String] = ["origin": origin]
        let cleanedModelName = modelNameOverride?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !cleanedModelName.isEmpty {
            metadata["model_name"] = cleanedModelName
        }

        let body: [String: AnyEncodable] = [
            "session_id": AnyEncodable(sessionID),
            "text": AnyEncodable(text),
            "metadata": AnyEncodable(metadata),
        ]
        let payload: MessagePayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/messages",
            method: "POST",
            body: body,
            timeout: 900
        )
        return ChatMessage(
            id: payload.id,
            role: ChatRole(rawValue: payload.role.lowercased()) ?? .assistant,
            content: payload.content,
            createdAt: parseDate(payload.created_at),
            attachments: payload.attachments.map {
                MessageAttachment(
                    filename: $0.filename,
                    contentType: $0.content_type,
                    downloadURL: $0.download_url,
                    sourceURL: $0.url
                )
            }
        )
    }

    func listModelNames(config: APIConfiguration) async throws -> [String] {
        let payload: [ModelPayload] = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/models",
            method: "GET",
            body: Optional<Int>.none
        )
        return payload.map(\.name).sorted()
    }

    func setSessionModel(config: APIConfiguration, sessionID: String, modelName: String) async throws -> String {
        let body = ["model_name": modelName]
        let payload: SessionModelSetPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/sessions/\(sessionID)/model",
            method: "POST",
            body: body
        )
        return payload.model
    }

    func pendingToolRuns(config: APIConfiguration, sessionID: String) async throws -> [ToolRunStatus] {
        let payload: [ToolRunPayload] = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/tools?status=pending&limit=200",
            method: "GET",
            body: Optional<Int>.none
        )
        return payload
            .filter { $0.session_id == sessionID }
            .sorted(by: { $0.created_at > $1.created_at })
            .map {
                ToolRunStatus(
                    id: $0.id,
                    sessionID: $0.session_id,
                    tool: $0.tool,
                    status: $0.status,
                    createdAt: parseDate($0.created_at),
                    requestedBy: $0.requested_by,
                    input: $0.input ?? [:],
                    reasoning: $0.reasoning
                )
            }
    }

    func pendingUserPrompts(config: APIConfiguration, sessionID: String) async throws -> [PendingUserPrompt] {
        let payload: [UserPromptPayload] = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/user-prompts?session_id=\(sessionID)",
            method: "GET",
            body: Optional<Int>.none
        )
        return payload
            .filter { $0.session_id == sessionID }
            .sorted(by: { $0.created_at > $1.created_at })
            .map {
                PendingUserPrompt(
                    id: $0.id,
                    sessionID: $0.session_id,
                    question: $0.question,
                    choices: $0.choices,
                    allowFreeText: $0.allow_free_text,
                    status: $0.status,
                    createdAt: parseDate($0.created_at)
                )
            }
    }

    func approveToolRun(config: APIConfiguration, toolRunID: String, decidedBy: String) async throws {
        let body = ["approved_by": decidedBy]
        let _: ToolApprovalResultPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/tools/\(toolRunID)/approve",
            method: "POST",
            body: body
        )
    }

    func denyToolRun(config: APIConfiguration, toolRunID: String, decidedBy: String) async throws {
        let body = ["approved_by": decidedBy]
        let _: ToolApprovalResultPayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/tools/\(toolRunID)/deny",
            method: "POST",
            body: body
        )
    }

    func executeCommand(
        config: APIConfiguration,
        command: String,
        args: [String: String] = [:],
        origin: String = "ios"
    ) async throws -> CommandResult {
        let body: [String: AnyEncodable] = [
            "command": AnyEncodable(command),
            "origin": AnyEncodable(origin),
            "args": AnyEncodable(args),
        ]
        let payload: CommandExecutePayload = try await requestJSON(
            baseURL: config.baseURL,
            token: config.token,
            path: "/v1/commands/execute",
            method: "POST",
            body: body
        )
        return CommandResult(ok: payload.ok, message: payload.message, data: payload.data)
    }

    func resolvedURL(config: APIConfiguration, rawURL: String) throws -> URL {
        let trimmed = rawURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let url = URL(string: trimmed), url.scheme != nil {
            return normalizeLocalhost(url)
        }
        let request = try buildRequest(baseURL: config.baseURL, path: trimmed, method: "GET", token: config.token)
        guard let url = request.url else {
            throw APIError.invalidBaseURL
        }
        return url
    }

    func attachmentData(config: APIConfiguration, rawURL: String) async throws -> Data {
        let request = try buildRequest(baseURL: config.baseURL, path: rawURL, method: "GET", token: config.token)
        let (data, response) = try await session.data(for: request)
        try ensureSuccess(response: response, data: data)
        return data
    }

    func downloadAttachmentFile(
        config: APIConfiguration,
        rawURL: String,
        suggestedFilename: String
    ) async throws -> URL {
        let data = try await attachmentData(config: config, rawURL: rawURL)
        let rootDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("SkitterAttachments", isDirectory: true)
        try FileManager.default.createDirectory(at: rootDirectory, withIntermediateDirectories: true)

        let sanitizedFilename = sanitizeFilename(suggestedFilename)
        let exportDirectory = rootDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: exportDirectory, withIntermediateDirectories: true)

        let destinationURL = exportDirectory.appendingPathComponent(sanitizedFilename)
        try data.write(to: destinationURL, options: [.atomic])
        return destinationURL
    }

    private func requestJSON<T: Decodable, B: Encodable>(
        baseURL: String,
        token: String?,
        path: String,
        method: String,
        body: B?,
        timeout: TimeInterval = 120
    ) async throws -> T {
        var request = try buildRequest(baseURL: baseURL, path: path, method: method, token: token)
        request.timeoutInterval = timeout
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        try ensureSuccess(response: response, data: data)
        return try decode(T.self, from: data)
    }

    private func buildRequest(
        baseURL: String,
        path: String,
        method: String,
        token: String?
    ) throws -> URLRequest {
        let url = try buildURL(baseURL: baseURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let token {
            let cleaned = token.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleaned.isEmpty else {
                throw APIError.missingAuthToken
            }
            request.setValue("Bearer \(cleaned)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func buildURL(baseURL: String, path: String) throws -> URL {
        let cleanedBase = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let raw = URL(string: cleanedBase) else {
            throw APIError.invalidBaseURL
        }
        let normalized = normalizeLocalhost(raw)
        let trimmedPath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let parts = trimmedPath.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        let pathPart = parts.isEmpty ? "" : String(parts[0])
        let basePathURL = pathPart.isEmpty ? normalized : normalized.appendingPathComponent(pathPart)
        guard parts.count > 1 else {
            return basePathURL
        }
        var components = URLComponents(url: basePathURL, resolvingAgainstBaseURL: false)
        components?.percentEncodedQuery = String(parts[1])
        guard let finalURL = components?.url else {
            throw APIError.invalidBaseURL
        }
        return finalURL
    }

    private func normalizeLocalhost(_ url: URL) -> URL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        if components.host?.lowercased() == "localhost" {
            components.host = "127.0.0.1"
        }
        return components.url ?? url
    }

    private func ensureSuccess(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw APIError.http(-1, "Invalid response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Request failed."
            throw APIError.http(http.statusCode, message)
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    private func attachmentsFromMeta(_ meta: [String: JSONValue], messageID: String) -> [MessageAttachment] {
        guard let attachmentsValue = meta["attachments"] else { return [] }
        guard case let .array(values) = attachmentsValue else { return [] }
        return values.enumerated().compactMap { offset, entry in
            guard case let .object(payload) = entry else { return nil }
            let filename = payload["filename"]?.stringValue ?? "attachment"
            let contentType = payload["content_type"]?.stringValue ?? "application/octet-stream"
            let downloadURL = payload["download_url"]?.stringValue
                ?? "/v1/messages/\(messageID)/attachments/\(offset)"
            let sourceURL = payload["url"]?.stringValue
            return MessageAttachment(
                filename: filename,
                contentType: contentType,
                downloadURL: downloadURL,
                sourceURL: sourceURL
            )
        }
    }

    private func parseDate(_ value: String) -> Date {
        if let date = Self.isoFormatterWithFractionalSeconds.date(from: value) {
            return date
        }
        if let date = Self.isoFormatter.date(from: value) {
            return date
        }
        return Date()
    }

    private func sanitizeFilename(_ filename: String) -> String {
        let trimmed = filename.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = trimmed.isEmpty ? "attachment" : trimmed
        let invalidCharacters = CharacterSet(charactersIn: "/:\\?%*|\"<>")
        let components = fallback.components(separatedBy: invalidCharacters)
        let sanitized = components.joined(separator: "-")
        return sanitized.isEmpty ? "attachment" : sanitized
    }
}

private struct SessionModelSetPayload: Decodable {
    let model: String
}

private struct ToolApprovalResultPayload: Decodable {
    let id: String
    let status: String
}

private struct AnyEncodable: Encodable {
    private let encodeClosure: (Encoder) throws -> Void

    init<T: Encodable>(_ value: T) {
        self.encodeClosure = value.encode
    }

    func encode(to encoder: Encoder) throws {
        try encodeClosure(encoder)
    }
}
