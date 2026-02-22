#!/usr/bin/env swift

import AppKit
import Foundation

enum IconGenerationError: LocalizedError {
    case missingOutputPath
    case symbolUnavailable
    case encodingFailed

    var errorDescription: String? {
        switch self {
        case .missingOutputPath:
            return "Usage: generate_app_icon.swift <output_png_path>"
        case .symbolUnavailable:
            return "Could not load SF Symbol: bolt.circle"
        case .encodingFailed:
            return "Could not encode generated icon as PNG."
        }
    }
}

func main() throws {
    guard CommandLine.arguments.count == 2 else {
        throw IconGenerationError.missingOutputPath
    }

    let outputURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: false)
    try FileManager.default.createDirectory(
        at: outputURL.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )

    let canvasSide: CGFloat = 1024
    let symbolSide: CGFloat = 700
    let canvasSize = NSSize(width: canvasSide, height: canvasSide)

    guard let symbol = NSImage(systemSymbolName: "bolt.circle", accessibilityDescription: "Skitter icon") else {
        throw IconGenerationError.symbolUnavailable
    }

    let symbolConfig = NSImage.SymbolConfiguration(pointSize: symbolSide, weight: .semibold)
        .applying(NSImage.SymbolConfiguration(paletteColors: [.white, .systemBlue]))
    let configuredSymbol = symbol.withSymbolConfiguration(symbolConfig) ?? symbol

    let image = NSImage(size: canvasSize)
    image.lockFocus()
    NSColor.clear.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: canvasSize)).fill()

    // Render an opaque dark app-tile background so the symbol remains visible.
    let tileInset: CGFloat = 74
    let tileRect = NSRect(
        x: tileInset,
        y: tileInset,
        width: canvasSide - (tileInset * 2),
        height: canvasSide - (tileInset * 2)
    )
    let tileCornerRadius: CGFloat = 200
    let tilePath = NSBezierPath(roundedRect: tileRect, xRadius: tileCornerRadius, yRadius: tileCornerRadius)
    let tileGradient = NSGradient(
        starting: NSColor(srgbRed: 0.16, green: 0.16, blue: 0.18, alpha: 1),
        ending: NSColor(srgbRed: 0.03, green: 0.03, blue: 0.05, alpha: 1)
    )
    tileGradient?.draw(in: tilePath, angle: -90)

    NSColor(white: 1.0, alpha: 0.08).setStroke()
    tilePath.lineWidth = 2
    tilePath.stroke()

    let drawRect = NSRect(
        x: (canvasSide - symbolSide) / 2,
        y: (canvasSide - symbolSide) / 2,
        width: symbolSide,
        height: symbolSide
    )
    configuredSymbol.draw(in: drawRect, from: .zero, operation: .sourceOver, fraction: 1.0)
    image.unlockFocus()

    guard
        let tiffData = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiffData),
        let pngData = bitmap.representation(using: .png, properties: [:])
    else {
        throw IconGenerationError.encodingFailed
    }

    try pngData.write(to: outputURL, options: .atomic)
}

do {
    try main()
} catch {
    fputs("Icon generation failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
