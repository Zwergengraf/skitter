import AppKit
import SwiftUI

struct CommandInputTextView: NSViewRepresentable {
    @Binding var text: String
    var onSubmit: () -> Void
    var onEscape: (() -> Void)? = nil

    final class SubmitTextView: NSTextView {
        var onSubmit: (() -> Void)?
        var onEscape: (() -> Void)?

        override func keyDown(with event: NSEvent) {
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
        textView.font = NSFont.systemFont(ofSize: NSFont.systemFontSize)
        textView.backgroundColor = .clear
        textView.textContainerInset = NSSize(width: 8, height: 8)
        textView.onSubmit = onSubmit
        textView.onEscape = onEscape
        textView.string = text
        scroll.documentView = textView

        return scroll
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? SubmitTextView else { return }
        if textView.string != text {
            textView.string = text
        }
        textView.onSubmit = onSubmit
        textView.onEscape = onEscape
    }
}
