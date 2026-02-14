import AppKit
import SwiftUI

@MainActor
final class ChatWindowController: NSObject, NSPopoverDelegate {
    private let state: AppState
    private let chatPopover = NSPopover()
    private var keyMonitor: Any?

    init(state: AppState) {
        self.state = state
        super.init()

        let content = ChatView(state: state)
        let host = NSHostingController(rootView: content)
        chatPopover.contentViewController = host
        chatPopover.behavior = .transient
        chatPopover.animates = true
        chatPopover.contentSize = NSSize(width: 540, height: 660)
        chatPopover.delegate = self
    }

    func toggle(relativeTo button: NSStatusBarButton?) {
        guard let button else { return }
        if chatPopover.isShown {
            chatPopover.performClose(nil)
            state.setChatWindowVisible(false)
            removeKeyMonitor()
            return
        }
        chatPopover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        state.setChatWindowVisible(true)
        installKeyMonitor()
        state.markChatOpened()
        Task { @MainActor in
            _ = try? await state.ensureSession(forceNew: false)
            state.markChatOpened()
        }
    }

    func close() {
        chatPopover.performClose(nil)
        state.setChatWindowVisible(false)
        removeKeyMonitor()
    }

    private func installKeyMonitor() {
        removeKeyMonitor()
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, self.chatPopover.isShown else { return event }
            if event.keyCode == 53 { // Escape
                self.chatPopover.performClose(nil)
                self.state.setChatWindowVisible(false)
                self.removeKeyMonitor()
                return nil
            }
            return event
        }
    }

    private func removeKeyMonitor() {
        if let keyMonitor {
            NSEvent.removeMonitor(keyMonitor)
            self.keyMonitor = nil
        }
    }

    func popoverDidClose(_ notification: Notification) {
        state.setChatWindowVisible(false)
        removeKeyMonitor()
    }
}
