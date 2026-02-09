import Foundation

@MainActor
struct APIClient {
    enum APIError: LocalizedError {
        case invalidBaseURL
        case missingAPIKey
        case http(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .invalidBaseURL:
                return "Invalid API URL"
            case .missingAPIKey:
                return "API key is required"
            case let .http(code, message):
                return "HTTP \(code): \(message)"
            case let .decoding(message):
                return "Decoding error: \(message)"
            }
        }
    }

    private let settings: SettingsStore
    private let session: URLSession

    init(settings: SettingsStore, session: URLSession = .shared) {
        self.settings = settings
        self.session = session
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
        let body = SessionCreateBody(user_id: settings.userID, origin: origin, reuse_active: reuseActive)
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
            let date = ISO8601DateFormatter().date(from: item.created_at) ?? Date()
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
        let body = MessageCreateBody(session_id: sessionID, user_id: settings.userID, text: text, metadata: [:])
        let payload: MessagePayload = try await requestJSON(
            path: "/v1/messages",
            method: "POST",
            body: body,
            requiresAPIKey: true
        )
        let date = ISO8601DateFormatter().date(from: payload.created_at) ?? Date()
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

    func latestToolRun(sessionID: String) async throws -> ToolRunStatus? {
        let payload: [ToolRunPayload] = try await requestJSON(
            path: "/v1/tools?limit=200",
            method: "GET",
            body: Optional<Int>.none,
            requiresAPIKey: true
        )
        let filtered = payload.filter { $0.session_id == sessionID }
        guard let latest = filtered.max(by: { $0.created_at < $1.created_at }) else {
            return nil
        }
        return ToolRunStatus(
            id: latest.id,
            sessionID: latest.session_id,
            tool: latest.tool,
            status: latest.status,
            createdAt: latest.created_at
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
        let key = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if !key.isEmpty {
            request.setValue(key, forHTTPHeaderField: "X-API-Key")
        }
        let (data, response) = try await session.data(for: request)
        try ensureHTTP200(response: response, data: data)
        return data
    }

    private func requestJSON<T: Decodable, B: Encodable>(
        path: String,
        method: String,
        body: B?,
        requiresAPIKey: Bool
    ) async throws -> T {
        var request = try buildRequest(path: path, method: method, requiresAPIKey: requiresAPIKey)
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
                throw APIError.missingAPIKey
            }
            request.setValue(key, forHTTPHeaderField: "X-API-Key")
        }
        return request
    }

    private func url(path: String) throws -> URL {
        let base = settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let baseURL = URL(string: base) else {
            throw APIError.invalidBaseURL
        }
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
            return url
        }
        return try url(path: trimmed)
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
}

private struct HealthPayload: Decodable {
    let status: String
}

private struct SessionCreateBody: Encodable {
    let user_id: String
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
    let user_id: String
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
