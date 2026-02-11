import Foundation

@MainActor
struct APIClient {
    enum APIError: LocalizedError {
        case invalidBaseURL
        case missingAuthToken
        case http(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .invalidBaseURL:
                return "Invalid API URL"
            case .missingAuthToken:
                return "Access token is required"
            case let .http(code, message):
                return "HTTP \(code): \(message)"
            case let .decoding(message):
                return "Decoding error: \(message)"
            }
        }
    }

    private let settings: SettingsStore
    private let session: URLSession
    private static let iso8601FormatterWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let iso8601Formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    init(settings: SettingsStore, session: URLSession? = nil) {
        self.settings = settings
        self.session = session ?? Self.makeDefaultSession()
    }

    private static func makeDefaultSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        // Long-running agent requests can exceed URLSession shared defaults.
        configuration.timeoutIntervalForRequest = 900
        configuration.timeoutIntervalForResource = 3600
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }

    func health() async throws -> Bool {
        let url = try url(path: "/health")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        let (data, response) = try await session.data(for: request)
        try ensureHTTP200(response: response, data: data)
        let payload = try decode(HealthPayload.self, from: data)
        return payload.status.lowercased() == "ok"
    }

    func createOrResumeSession(origin: String, reuseActive: Bool) async throws -> String {
        let body = SessionCreateBody(origin: origin, reuse_active: reuseActive)
        let payload: SessionPayload = try await requestJSON(
            path: "/v1/sessions",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
        return payload.id
    }

    func sessionSnapshot(sessionID: String) async throws -> SessionSnapshot {
        let payload: SessionPayload = try await requestJSON(
            path: "/v1/sessions/\(sessionID)",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        return SessionSnapshot(
            id: payload.id,
            contextTokens: payload.last_input_tokens ?? 0,
            totalTokens: payload.total_tokens ?? 0,
            totalCost: payload.total_cost ?? 0,
            modelName: payload.last_model ?? payload.model ?? "default"
        )
    }

    func sessionDetail(sessionID: String) async throws -> [ChatMessage] {
        let payload: SessionDetailPayload = try await requestJSON(
            path: "/v1/sessions/\(sessionID)/detail",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        return payload.messages.compactMap { item in
            let role: ChatRole
            switch item.role.lowercased() {
            case "user":
                role = .user
            case "assistant":
                role = .assistant
            case "system":
                role = .system
            default:
                role = .other
            }
            let date = parseDate(item.created_at)
            let attachments = (item.meta.attachments ?? []).enumerated().map { idx, payload in
                let resolvedDownload = payload.download_url ?? "/v1/messages/\(item.id)/attachments/\(idx)"
                return MessageAttachment(
                    filename: payload.filename,
                    contentType: payload.content_type,
                    downloadURL: resolvedDownload,
                    sourceURL: payload.url
                )
            }
            return ChatMessage(id: item.id, role: role, content: item.content, createdAt: date, attachments: attachments)
        }
    }

    func sendMessage(sessionID: String, text: String) async throws -> ChatMessage {
        let body = MessageCreateBody(session_id: sessionID, text: text, metadata: [:])
        let payload: MessagePayload = try await requestJSON(
            path: "/v1/messages",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
        let date = parseDate(payload.created_at)
        let attachments = payload.attachments.map {
            MessageAttachment(
                filename: $0.filename,
                contentType: $0.content_type,
                downloadURL: $0.download_url,
                sourceURL: $0.url
            )
        }
        return ChatMessage(id: payload.id, role: .assistant, content: payload.content, createdAt: date, attachments: attachments)
    }

    func pendingToolCount() async throws -> Int {
        let payload: [ToolRunPayload] = try await requestJSON(
            path: "/v1/tools?status=pending",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        return payload.count
    }

    func latestToolRun(sessionID: String, since: Date? = nil) async throws -> ToolRunStatus? {
        let payload: [ToolRunPayload] = try await requestJSON(
            path: "/v1/tools?limit=200",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        let filtered = payload.compactMap { item -> (ToolRunPayload, Date)? in
            guard item.session_id == sessionID else { return nil }
            let createdAt = parseDate(item.created_at)
            if let since, createdAt < since {
                return nil
            }
            return (item, createdAt)
        }
        guard let latest = filtered.max(by: { $0.1 < $1.1 }) else {
            return nil
        }
        return ToolRunStatus(
            id: latest.0.id,
            sessionID: latest.0.session_id,
            tool: latest.0.tool,
            status: latest.0.status,
            createdAt: latest.1,
            requestedBy: latest.0.requested_by,
            input: latest.0.input ?? [:]
        )
    }

    func pendingToolRuns(sessionID: String) async throws -> [ToolRunStatus] {
        let payload: [ToolRunPayload] = try await requestJSON(
            path: "/v1/tools?status=pending&limit=200",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
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
                    input: $0.input ?? [:]
                )
            }
    }

    func approveToolRun(toolRunID: String, decidedBy: String) async throws {
        let body = ToolApprovalBody(approved_by: decidedBy)
        let _: ToolApprovalResult = try await requestJSON(
            path: "/v1/tools/\(toolRunID)/approve",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
    }

    func denyToolRun(toolRunID: String, decidedBy: String) async throws {
        let body = ToolApprovalBody(approved_by: decidedBy)
        let _: ToolApprovalResult = try await requestJSON(
            path: "/v1/tools/\(toolRunID)/deny",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
    }

    func listModelNames() async throws -> [String] {
        let payload: [ModelPayload] = try await requestJSON(
            path: "/v1/models",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        return payload.map { $0.name }
    }

    func setSessionModel(sessionID: String, modelName: String) async throws -> String {
        let body = SessionModelSetBody(model_name: modelName)
        let payload: SessionModelSetPayload = try await requestJSON(
            path: "/v1/sessions/\(sessionID)/model",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
        return payload.model
    }

    func fetchData(from rawURL: String) async throws -> Data {
        let url = try resolveURL(from: rawURL)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        applyAuthHeader(&request)
        let (data, response) = try await session.data(for: request)
        try ensureHTTP200(response: response, data: data)
        return data
    }

    func bootstrap(
        bootstrapCode: String,
        displayName: String,
        deviceName: String?,
        deviceType: String
    ) async throws -> (token: String, user: AuthUser) {
        let body = AuthBootstrapBody(
            bootstrap_code: bootstrapCode,
            display_name: displayName,
            device_name: deviceName,
            device_type: deviceType
        )
        let payload: AuthTokenPayload = try await requestJSON(
            path: "/v1/auth/bootstrap",
            method: "POST",
            body: body,
            requiresAPIKey: false
        )
        return (payload.token, payload.user.toDomain())
    }

    func pair(
        pairCode: String,
        deviceName: String?,
        deviceType: String
    ) async throws -> (token: String, user: AuthUser) {
        let body = AuthPairBody(
            pair_code: pairCode,
            device_name: deviceName,
            device_type: deviceType
        )
        let payload: AuthTokenPayload = try await requestJSON(
            path: "/v1/auth/pair/complete",
            method: "POST",
            body: body,
            requiresAPIKey: false
        )
        return (payload.token, payload.user.toDomain())
    }

    func authMe() async throws -> AuthUser {
        let payload: AuthUserPayload = try await requestJSON(
            path: "/v1/auth/me",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        return payload.toDomain()
    }

    private func requestJSON<T: Decodable, B: Encodable>(
        path: String,
        method: String,
        body: B?,
        requiresAPIKey: Bool
    ) async throws -> T {
        var request = try buildRequest(path: path, method: method, requiresAPIKey: requiresAPIKey)
        if path.hasPrefix("/v1/messages") && method.uppercased() == "POST" {
            request.timeoutInterval = 900
        } else {
            request.timeoutInterval = 120
        }
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        try ensureHTTP200(response: response, data: data)
        return try decode(T.self, from: data)
    }

    private func buildRequest(path: String, method: String, requiresAPIKey: Bool) throws -> URLRequest {
        let url = try url(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        if requiresAPIKey {
            let key = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty else {
                throw APIError.missingAuthToken
            }
            request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func applyAuthHeader(_ request: inout URLRequest) {
        let token = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if token.isEmpty {
            return
        }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    private func url(path: String) throws -> URL {
        let baseURL = try normalizedBaseURL()
        let trimmed = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let parts = trimmed.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        let pathPart = String(parts[0])
        let pathURL = pathPart.isEmpty ? baseURL : baseURL.appendingPathComponent(pathPart)
        guard parts.count > 1 else {
            return pathURL
        }
        var components = URLComponents(url: pathURL, resolvingAgainstBaseURL: false)
        components?.percentEncodedQuery = String(parts[1])
        guard let finalURL = components?.url else {
            throw APIError.invalidBaseURL
        }
        return finalURL
    }

    private func resolveURL(from rawURL: String) throws -> URL {
        let trimmed = rawURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let url = URL(string: trimmed), url.scheme != nil {
            return normalizeLocalhost(url)
        }
        return try url(path: trimmed)
    }

    private func normalizedBaseURL() throws -> URL {
        let base = settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let raw = URL(string: base) else {
            throw APIError.invalidBaseURL
        }
        return normalizeLocalhost(raw)
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

    private func ensureHTTP200(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw APIError.http(-1, "Invalid response")
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "request failed"
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

    private func parseDate(_ raw: String) -> Date {
        if let date = Self.iso8601FormatterWithFractionalSeconds.date(from: raw) {
            return date
        }
        if let date = Self.iso8601Formatter.date(from: raw) {
            return date
        }
        return Date()
    }
}

private struct HealthPayload: Decodable {
    let status: String
}

private struct SessionCreateBody: Encodable {
    let origin: String
    let reuse_active: Bool
}

private struct SessionPayload: Decodable {
    let id: String
    let model: String?
    let total_cost: Double?
    let total_tokens: Int?
    let last_input_tokens: Int?
    let last_model: String?
}

private struct MessageCreateBody: Encodable {
    let session_id: String
    let text: String
    let metadata: [String: String]
}

private struct AttachmentPayload: Decodable {
    let filename: String
    let content_type: String
    let url: String?
    let download_url: String?
}

private struct MessagePayload: Decodable {
    let id: String
    let content: String
    let created_at: String
    let attachments: [AttachmentPayload]
}

private struct ToolRunPayload: Decodable {
    let id: String
    let session_id: String
    let tool: String
    let status: String
    let created_at: String
    let requested_by: String?
    let input: [String: JSONValue]?
}

private struct ModelPayload: Decodable {
    let name: String
}

private struct SessionModelSetBody: Encodable {
    let model_name: String
}

private struct SessionModelSetPayload: Decodable {
    let session_id: String
    let model: String
}

private struct SessionDetailPayload: Decodable {
    let messages: [SessionMessagePayload]
}

private struct SessionMessagePayload: Decodable {
    let id: String
    let role: String
    let content: String
    let created_at: String
    let meta: SessionMessageMeta
}

private struct SessionMessageMeta: Decodable {
    let attachments: [AttachmentPayload]?
}

private struct ToolApprovalBody: Encodable {
    let approved_by: String
}

private struct ToolApprovalResult: Decodable {
    let id: String
    let status: String
    let approved_by: String?
}

private struct AuthBootstrapBody: Encodable {
    let bootstrap_code: String
    let display_name: String
    let device_name: String?
    let device_type: String
}

private struct AuthPairBody: Encodable {
    let pair_code: String
    let device_name: String?
    let device_type: String
}

private struct AuthTokenPayload: Decodable {
    let token: String
    let user: AuthUserPayload
}

private struct AuthUserPayload: Decodable {
    let id: String
    let display_name: String
    let approved: Bool

    func toDomain() -> AuthUser {
        AuthUser(id: id, displayName: display_name, approved: approved)
    }
}
