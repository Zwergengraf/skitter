import XCTest
@testable import Skitter

final class SkitterCoreTests: XCTestCase {
    override func tearDown() {
        URLProtocolStub.handler = nil
        super.tearDown()
    }

    func testCommandMatcherReturnsAllCommandsForBareSlash() {
        let matches = CommandMatcher.filter("/")
        XCTAssertEqual(matches.map(\.id), LocalCommand.all.map(\.id))
    }

    func testCommandMatcherFiltersByPrefix() {
        let matches = CommandMatcher.filter("/schedule_")
        XCTAssertEqual(matches.map(\.id), ["schedule_list", "schedule_delete", "schedule_pause", "schedule_resume"])
    }

    func testCommandMatcherReturnsNothingWithoutSlashPrefix() {
        XCTAssertTrue(CommandMatcher.filter("model").isEmpty)
    }

    func testMarkdownRepresentationIncludesAttachmentLinks() {
        let message = ChatMessage(
            id: "message-1",
            role: .assistant,
            content: "Here is the result.",
            createdAt: Date(timeIntervalSince1970: 0),
            attachments: [
                MessageAttachment(
                    filename: "diagram.png",
                    contentType: "image/png",
                    downloadURL: "https://example.com/diagram.png",
                    sourceURL: nil
                ),
                MessageAttachment(
                    filename: "report.pdf",
                    contentType: "application/pdf",
                    downloadURL: nil,
                    sourceURL: "/files/report.pdf"
                ),
            ]
        )

        XCTAssertEqual(
            message.markdownRepresentation,
            """
            **Skitter**

            Here is the result.

            ![diagram.png](https://example.com/diagram.png)
            [report.pdf](/files/report.pdf)
            """
        )
    }

    func testShareTextFallsBackForEmptyMessages() {
        let message = ChatMessage.local(role: .assistant, content: "   ")
        XCTAssertEqual(message.shareText, "(empty)")
    }

    func testSecretRefsExtractOnlyStringValues() {
        let toolRun = ToolRunStatus(
            id: "tool-1",
            sessionID: "session-1",
            tool: "functions.exec_command",
            status: "pending",
            createdAt: Date(timeIntervalSince1970: 0),
            requestedBy: "ios",
            input: [
                "secret_refs": .array([.string("prod/skitter"), .number(2), .string("staging/skitter")]),
            ],
            reasoning: []
        )

        XCTAssertEqual(toolRun.secretRefs, ["prod/skitter", "staging/skitter"])
    }

    func testDownloadAttachmentFileKeepsCleanFilename() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let client = APIClient(session: session)
        let payload = Data("archive".utf8)

        URLProtocolStub.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token")
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/zip"]
            )!
            return (response, payload)
        }

        let fileURL = try await client.downloadAttachmentFile(
            config: APIConfiguration(baseURL: "https://example.com", token: "token"),
            rawURL: "/files/skitter-export.zip",
            suggestedFilename: "skitter-export.zip"
        )
        defer {
            try? FileManager.default.removeItem(at: fileURL.deletingLastPathComponent())
        }

        XCTAssertEqual(fileURL.lastPathComponent, "skitter-export.zip")
        XCTAssertEqual(try Data(contentsOf: fileURL), payload)
    }

    @MainActor
    func testSettingsStorePersistsSpeechSynthesisVoicePreference() {
        let suiteName = "io.skitter.tests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suiteName) else {
            XCTFail("Expected isolated defaults suite")
            return
        }
        defer {
            defaults.removePersistentDomain(forName: suiteName)
        }

        let store = SettingsStore(defaults: defaults)
        store.speechSynthesisVoiceIdentifier = "com.apple.voice.compact.de-DE.Anna"
        store.speechSynthesisProvider = .openAI
        store.openAIBaseURL = "https://tts.example.com/v1"
        store.openAITTSModel = "gpt-4o-mini-tts"
        store.openAITTSVoice = "verse"

        let reloaded = SettingsStore(defaults: defaults)
        XCTAssertEqual(reloaded.speechSynthesisVoiceIdentifier, "com.apple.voice.compact.de-DE.Anna")
        XCTAssertEqual(reloaded.effectiveSpeechSynthesisVoiceIdentifier, "com.apple.voice.compact.de-DE.Anna")
        XCTAssertEqual(reloaded.speechSynthesisProvider, .openAI)
        XCTAssertEqual(reloaded.openAIBaseURL, "https://tts.example.com/v1")
        XCTAssertEqual(reloaded.openAITTSModel, "gpt-4o-mini-tts")
        XCTAssertEqual(reloaded.openAITTSVoice, "verse")
    }
}

private final class URLProtocolStub: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }

        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {
    }
}
