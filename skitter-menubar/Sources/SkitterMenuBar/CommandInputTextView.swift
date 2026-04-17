import AppKit
import SwiftUI

struct CommandInputTextView: NSViewRepresentable {
    @Binding var text: String
    var onSubmit: () -> Void
    var onEscape: (() -> Void)? = nil
    @Environment(\.colorScheme) private var colorScheme

    final class SubmitTextView: NSTextView {
        var onSubmit: (() -> Void)?
        var onEscape: (() -> Void)?

        override func keyDown(with event: NSEvent) {
            if hasMarkedText() {
                super.keyDown(with: event)
                return
            }
            if event.keyCode == 36 { // Return
                if event.modifierFlags.contains(.shift) {
                    insertNewline(nil)
                } else {
                    onSubmit?()
                }
                return
            }
            if event.keyCode == 53 { // Escape
                onEscape?()
                return
            }
            super.keyDown(with: event)
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: CommandInputTextView

        init(parent: CommandInputTextView) {
            self.parent = parent
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textView.string
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.borderType = .noBorder
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false

        let textView = SubmitTextView()
        textView.delegate = context.coordinator
        textView.isRichText = false
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticSpellingCorrectionEnabled = false
        textView.isContinuousSpellCheckingEnabled = false
        textView.backgroundColor = .clear
        textView.textContainerInset = NSSize(width: 8, height: 8)
        textView.onSubmit = onSubmit
        textView.onEscape = onEscape
        textView.string = text
        applyAppearance(to: textView)
        scroll.documentView = textView

        return scroll
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? SubmitTextView else { return }
        context.coordinator.parent = self
        if textView.string != text && !textView.hasMarkedText() {
            textView.string = text
        }
        textView.onSubmit = onSubmit
        textView.onEscape = onEscape
        applyAppearance(to: textView)
    }

    private func applyAppearance(to textView: NSTextView) {
        let font = NSFont.systemFont(ofSize: NSFont.systemFontSize)
        let textColor: NSColor = colorScheme == .dark
            ? NSColor.white.withAlphaComponent(0.92)
            : .labelColor
        let markedBackgroundColor: NSColor = colorScheme == .dark
            ? NSColor.white.withAlphaComponent(0.18)
            : NSColor.controlAccentColor.withAlphaComponent(0.16)

        textView.font = font
        textView.textColor = textColor
        textView.insertionPointColor = textColor
        let typingAttributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: textColor
        ]
        if !textView.hasMarkedText() {
            textView.typingAttributes = typingAttributes
        }
        textView.markedTextAttributes = [
            .font: font,
            .foregroundColor: textColor,
            .backgroundColor: markedBackgroundColor,
            .underlineStyle: NSUnderlineStyle.single.rawValue,
            .underlineColor: NSColor.controlAccentColor
        ]
    }
}
