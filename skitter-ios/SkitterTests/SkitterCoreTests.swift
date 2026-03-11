import XCTest
@testable import Skitter

final class SkitterCoreTests: XCTestCase {
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
}
