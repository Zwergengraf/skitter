import Foundation
import SwiftUI

struct MarkdownMessageText: View {
    private final class SegmentCacheBox: NSObject {
        let segments: [Segment]

        init(segments: [Segment]) {
            self.segments = segments
        }
    }

    private struct TableData {
        let header: [String]
        let rows: [[String]]
    }

    private struct ListItemData {
        let marker: String
        let text: String
        let indentLevel: Int
    }

    private struct ListData {
        let items: [ListItemData]
    }

    private enum Segment: Identifiable {
        case markdown(id: Int, text: AttributedString)
        case code(id: Int, text: String)
        case table(id: Int, data: TableData)
        case list(id: Int, data: ListData)
        case blank(id: Int)

        var id: Int {
            switch self {
            case let .markdown(id, _):
                return id
            case let .code(id, _):
                return id
            case let .table(id, _):
                return id
            case let .list(id, _):
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
                case let .table(_, data):
                    tableView(data)
                case let .list(_, data):
                    listView(data)
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
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var nextSegmentID = 0
        var markdownLines: [String] = []

        func flushMarkdown() {
            guard !markdownLines.isEmpty else { return }
            let markdownText = markdownLines.joined(separator: "\n")
            let rendered: AttributedString
            if let parsed = try? AttributedString(
                markdown: markdownText,
                options: AttributedString.MarkdownParsingOptions(
                    interpretedSyntax: .full,
                    failurePolicy: .returnPartiallyParsedIfPossible
                )
            ) {
                rendered = parsed
            } else {
                rendered = AttributedString(markdownText)
            }
            out.append(.markdown(id: nextSegmentID, text: rendered))
            nextSegmentID += 1
            markdownLines.removeAll(keepingCapacity: true)
        }

        var index = 0
        while index < lines.count {
            let line = lines[index]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                flushMarkdown()
                index += 1
                var codeLines: [String] = []
                while index < lines.count {
                    let candidate = lines[index]
                    let candidateTrimmed = candidate.trimmingCharacters(in: .whitespaces)
                    if candidateTrimmed.hasPrefix("```") {
                        index += 1
                        break
                    }
                    codeLines.append(candidate)
                    index += 1
                }
                out.append(.code(id: nextSegmentID, text: codeLines.joined(separator: "\n")))
                nextSegmentID += 1
                continue
            }

            if line.isEmpty {
                flushMarkdown()
                out.append(.blank(id: nextSegmentID))
                nextSegmentID += 1
                index += 1
                continue
            }

            if let table = parseTable(lines: lines, startIndex: index) {
                flushMarkdown()
                out.append(.table(id: nextSegmentID, data: table.data))
                nextSegmentID += 1
                index = table.nextIndex
                continue
            }

            if let list = parseList(lines: lines, startIndex: index) {
                flushMarkdown()
                out.append(.list(id: nextSegmentID, data: list.data))
                nextSegmentID += 1
                index = list.nextIndex
                continue
            }

            markdownLines.append(line)
            index += 1
        }

        flushMarkdown()

        if out.isEmpty {
            return [.markdown(id: 0, text: AttributedString(""))]
        }
        return out
    }

    private static func parseTable(lines: [String], startIndex: Int) -> (data: TableData, nextIndex: Int)? {
        guard startIndex + 1 < lines.count else { return nil }
        let headerLine = lines[startIndex]
        let separatorLine = lines[startIndex + 1]
        guard headerLine.contains("|"), separatorLine.contains("|") else { return nil }
        guard isTableSeparator(separatorLine) else { return nil }

        let headerCells = splitTableRow(headerLine)
        guard headerCells.count >= 2 else { return nil }

        var rows: [[String]] = []
        var index = startIndex + 2
        while index < lines.count {
            let line = lines[index]
            if line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                break
            }
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                break
            }
            guard line.contains("|") else { break }
            let cells = splitTableRow(line)
            if cells.isEmpty {
                break
            }
            rows.append(normalizeTableRow(cells, toWidth: headerCells.count))
            index += 1
        }

        guard !rows.isEmpty else { return nil }
        let normalizedHeader = normalizeTableRow(headerCells, toWidth: headerCells.count)
        return (data: TableData(header: normalizedHeader, rows: rows), nextIndex: index)
    }

    private static func isTableSeparator(_ line: String) -> Bool {
        let rawCells = splitTableRow(line, trimCells: false)
        guard !rawCells.isEmpty else { return false }
        for raw in rawCells {
            let token = raw.replacingOccurrences(of: " ", with: "")
            guard !token.isEmpty else { continue }
            for scalar in token.unicodeScalars {
                if scalar != "-" && scalar != ":" {
                    return false
                }
            }
        }
        return true
    }

    private static func splitTableRow(_ line: String, trimCells: Bool = true) -> [String] {
        var working = line
        if working.hasPrefix("|") {
            working.removeFirst()
        }
        if working.hasSuffix("|") {
            working.removeLast()
        }

        return working.split(separator: "|", omittingEmptySubsequences: false).map { raw in
            let cell = String(raw)
            if trimCells {
                return cell.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            return cell
        }
    }

    private static func normalizeTableRow(_ row: [String], toWidth width: Int) -> [String] {
        if row.count == width {
            return row
        }
        if row.count > width {
            return Array(row.prefix(width))
        }
        return row + Array(repeating: "", count: width - row.count)
    }

    private static func parseList(lines: [String], startIndex: Int) -> (data: ListData, nextIndex: Int)? {
        guard startIndex < lines.count else { return nil }
        guard let first = parseListLine(lines[startIndex]) else { return nil }

        var items: [ListItemData] = [first]
        var index = startIndex + 1

        while index < lines.count {
            let line = lines[index]
            if line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                break
            }

            if let parsed = parseListLine(line) {
                items.append(parsed)
                index += 1
                continue
            }

            // Continuation line for previous bullet item.
            let continuation = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if continuation.isEmpty {
                break
            }
            if var last = items.popLast() {
                last = ListItemData(
                    marker: last.marker,
                    text: "\(last.text)\n\(continuation)",
                    indentLevel: last.indentLevel
                )
                items.append(last)
                index += 1
                continue
            }
            break
        }

        return (data: ListData(items: items), nextIndex: index)
    }

    private static func parseListLine(_ line: String) -> ListItemData? {
        let trimmedNewline = line.trimmingCharacters(in: .newlines)
        if trimmedNewline.isEmpty {
            return nil
        }

        let leadingSpaces = trimmedNewline.prefix { $0 == " " || $0 == "\t" }
        let leadingCount = leadingSpaces.reduce(0) { partial, char in
            partial + (char == "\t" ? 4 : 1)
        }
        let indentLevel = max(0, leadingCount / 2)
        let startIndex = trimmedNewline.index(trimmedNewline.startIndex, offsetBy: leadingSpaces.count)
        let body = String(trimmedNewline[startIndex...])

        let unorderedTaskUnchecked = ["- [ ] ", "* [ ] ", "+ [ ] "]
        if let prefix = unorderedTaskUnchecked.first(where: { body.hasPrefix($0) }) {
            let text = String(body.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            return ListItemData(marker: "☐", text: text, indentLevel: indentLevel)
        }

        let unorderedTaskChecked = ["- [x] ", "- [X] ", "* [x] ", "* [X] ", "+ [x] ", "+ [X] "]
        if let prefix = unorderedTaskChecked.first(where: { body.hasPrefix($0) }) {
            let text = String(body.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            return ListItemData(marker: "☑", text: text, indentLevel: indentLevel)
        }

        let unordered = ["- ", "* ", "+ "]
        if let prefix = unordered.first(where: { body.hasPrefix($0) }) {
            let text = String(body.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            return ListItemData(marker: "•", text: text, indentLevel: indentLevel)
        }

        var numberPart = ""
        var idx = body.startIndex
        while idx < body.endIndex, body[idx].isNumber {
            numberPart.append(body[idx])
            idx = body.index(after: idx)
        }
        if !numberPart.isEmpty, idx < body.endIndex, body[idx] == "." || body[idx] == ")" {
            idx = body.index(after: idx)
            if idx < body.endIndex, body[idx] == " " {
                idx = body.index(after: idx)
            }
            let text = String(body[idx...]).trimmingCharacters(in: .whitespacesAndNewlines)
            return ListItemData(marker: "\(numberPart).", text: text, indentLevel: indentLevel)
        }

        return nil
    }

    @ViewBuilder
    private func tableView(_ table: TableData) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 8) {
                GridRow {
                    ForEach(Array(table.header.enumerated()), id: \.offset) { _, cell in
                        Text(inlineMarkdown(cell))
                            .font(.caption.weight(.semibold))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                Rectangle()
                    .fill(Color.secondary.opacity(0.28))
                    .frame(height: 1)
                    .gridCellColumns(table.header.count)
                ForEach(Array(table.rows.enumerated()), id: \.offset) { _, row in
                    GridRow {
                        ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                            Text(inlineMarkdown(cell))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
            .padding(10)
        }
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.secondary.opacity(0.10))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
        )
    }

    private func inlineMarkdown(_ text: String) -> AttributedString {
        if let parsed = try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(
                interpretedSyntax: .inlineOnlyPreservingWhitespace,
                failurePolicy: .returnPartiallyParsedIfPossible
            )
        ) {
            return parsed
        }
        return AttributedString(text)
    }

    @ViewBuilder
    private func listView(_ list: ListData) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(Array(list.items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .top, spacing: 6) {
                    Text(item.marker)
                        .frame(minWidth: 16, alignment: .leading)
                    Text(inlineMarkdown(item.text))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.leading, CGFloat(item.indentLevel) * 12)
            }
        }
    }
}
