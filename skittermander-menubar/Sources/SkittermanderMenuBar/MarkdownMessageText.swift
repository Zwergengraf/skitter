import SwiftUI

struct MarkdownMessageText: View {
    private enum Segment: Identifiable {
        case markdown(id: UUID, text: AttributedString)
        case code(id: UUID, text: String)
        case blank(id: UUID)

        var id: UUID {
            switch self {
            case let .markdown(id, _):
                return id
            case let .code(id, _):
                return id
            case let .blank(id):
                return id
            }
        }
    }

    private let segments: [Segment]

    init(_ text: String) {
        let normalized = Self.normalizeNewlines(text)
        self.segments = Self.buildSegments(from: normalized)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(segments) { segment in
                switch segment {
                case let .markdown(_, text):
                    Text(text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                case let .code(_, text):
                    Text(text)
                        .font(.system(.body, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Color.secondary.opacity(0.12))
                        )
                case .blank:
                    Text(" ")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .font(.caption)
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static func normalizeNewlines(_ input: String) -> String {
        let normalized = input
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        if normalized.contains("\n") {
            return normalized
        }
        if normalized.contains("\\n") {
            return normalized.replacingOccurrences(of: "\\n", with: "\n")
        }
        return normalized
    }

    private static func buildSegments(from text: String) -> [Segment] {
        var out: [Segment] = []
        var inFence = false
        var codeLines: [String] = []

        func flushCode() {
            guard !codeLines.isEmpty else { return }
            let body = codeLines.joined(separator: "\n")
            out.append(.code(id: UUID(), text: body))
            codeLines.removeAll(keepingCapacity: true)
        }

        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                if inFence {
                    inFence = false
                    flushCode()
                } else {
                    inFence = true
                }
                continue
            }

            if inFence {
                codeLines.append(line)
                continue
            }

            if line.isEmpty {
                out.append(.blank(id: UUID()))
                continue
            }

            let displayLine = rewriteListPrefixIfNeeded(line)
            if let rendered = try? AttributedString(
                markdown: displayLine,
                options: AttributedString.MarkdownParsingOptions(
                    interpretedSyntax: .full,
                    failurePolicy: .returnPartiallyParsedIfPossible
                )
            ) {
                out.append(.markdown(id: UUID(), text: rendered))
            } else {
                out.append(.markdown(id: UUID(), text: AttributedString(displayLine)))
            }
        }

        if inFence {
            flushCode()
        }

        if out.isEmpty {
            return [.markdown(id: UUID(), text: AttributedString(""))]
        }
        return out
    }

    private static func rewriteListPrefixIfNeeded(_ line: String) -> String {
        let indentEnd = line.firstIndex(where: { $0 != " " && $0 != "\t" }) ?? line.endIndex
        let indent = String(line[..<indentEnd])
        var remainder = String(line[indentEnd...])

        let uncheckedPrefixes = ["- [ ] ", "* [ ] ", "+ [ ] "]
        if let prefix = uncheckedPrefixes.first(where: { remainder.hasPrefix($0) }) {
            remainder.removeFirst(prefix.count)
            return "\(indent)☐ \(remainder)"
        }

        let checkedPrefixes = ["- [x] ", "- [X] ", "* [x] ", "* [X] ", "+ [x] ", "+ [X] "]
        if let prefix = checkedPrefixes.first(where: { remainder.hasPrefix($0) }) {
            remainder.removeFirst(prefix.count)
            return "\(indent)☑ \(remainder)"
        }

        let bulletPrefixes = ["- ", "* ", "+ "]
        if let prefix = bulletPrefixes.first(where: { remainder.hasPrefix($0) }) {
            remainder.removeFirst(prefix.count)
            return "\(indent)• \(remainder)"
        }

        return line
    }
}
