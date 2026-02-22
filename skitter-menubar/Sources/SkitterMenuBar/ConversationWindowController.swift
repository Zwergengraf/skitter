import AppKit
import SwiftUI

@MainActor
final class ConversationWindowController: NSObject, NSWindowDelegate {
    private let state: AppState
    private var windowController: NSWindowController?

    init(state: AppState) {
        self.state = state
        super.init()
    }

    func toggle() {
        if let window = windowController?.window, window.isVisible {
            close()
            return
        }
        show()
    }

    func show() {
        let controller = ensureWindowController()
        controller.showWindow(nil)
        controller.window?.makeKeyAndOrderFront(nil)
        state.setConversationWindowVisible(true)
        NSApp.activate(ignoringOtherApps: true)
    }

    func close() {
        state.setConversationWindowVisible(false)
        windowController?.close()
    }

    func windowWillClose(_ notification: Notification) {
        state.setConversationWindowVisible(false)
    }

    private func ensureWindowController() -> NSWindowController {
        if let windowController {
            return windowController
        }

        let root = ConversationView(state: state)
        let host = NSHostingController(rootView: root)

        let window = NSWindow(contentViewController: host)
        window.title = "Skitter Conversation"
        window.styleMask = [.titled, .closable, .fullSizeContentView]
        window.setContentSize(NSSize(width: 500, height: 700))
        window.minSize = NSSize(width: 460, height: 650)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isOpaque = false
        window.backgroundColor = .clear
        window.alphaValue = 1
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.level = .floating
        window.delegate = self

        let controller = NSWindowController(window: window)
        windowController = controller
        return controller
    }
}
