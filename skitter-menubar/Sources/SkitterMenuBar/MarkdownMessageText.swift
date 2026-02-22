import Foundation
import SwiftUI

struct MarkdownMessageText: View {
    private final class SegmentCacheBox: NSObject {
        let segments: [Segment]

        init(segments: [Segment]) {
            self.segments = segments
        }
    }

    private enum Segment: Identifiable {
        case markdown(id: Int, text: AttributedString)
        case code(id: Int, text: String)
        case blank(id: Int)

        var id: Int {
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
    private static let segmentCache: NSCache<NSString, SegmentCacheBox> = {
        let cache = NSCache<NSString, SegmentCacheBox>()
        cache.countLimit = 500
        return cache
    }()

    init(_ text: String) {
        let normalized = Self.normalizeNewlines(text)
        let cacheKey = normalized as NSString
        if let cached = Self.segmentCache.object(forKey: cacheKey) {
            self.segments = cached.segments
            return
        }
        let built = Self.buildSegments(from: normalized)
        self.segments = built
        Self.segmentCache.setObject(SegmentCacheBox(segments: built), forKey: cacheKey)
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
        var nextSegmentID = 0

        func flushCode() {
            guard !codeLines.isEmpty else { return }
            let body = codeLines.joined(separator: "\n")
            out.append(.code(id: nextSegmentID, text: body))
            nextSegmentID += 1
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
                out.append(.blank(id: nextSegmentID))
                nextSegmentID += 1
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
                out.append(.markdown(id: nextSegmentID, text: rendered))
            } else {
                out.append(.markdown(id: nextSegmentID, text: AttributedString(displayLine)))
            }
            nextSegmentID += 1
        }

        if inFence {
            flushCode()
        }

        if out.isEmpty {
            return [.markdown(id: 0, text: AttributedString(""))]
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
