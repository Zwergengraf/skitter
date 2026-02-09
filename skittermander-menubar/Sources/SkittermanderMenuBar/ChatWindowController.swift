import AppKit
import SwiftUI

@MainActor
final class ChatWindowController: NSObject {
    private let state: AppState
    private let chatPopover = NSPopover()

    init(state: AppState) {
        self.state = state
        super.init()

        let content = ChatView(state: state)
        let host = NSHostingController(rootView: content)
        chatPopover.contentViewController = host
        chatPopover.behavior = .transient
        chatPopover.animates = true
        chatPopover.contentSize = NSSize(width: 440, height: 540)
    }

    func toggle(relativeTo button: NSStatusBarButton?) {
        guard let button else { return }
        if chatPopover.isShown {
            chatPopover.performClose(nil)
            return
        }
        chatPopover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        Task { @MainActor in
            _ = try? await state.ensureSession(forceNew: false)
        }
    }

    func close() {
        chatPopover.performClose(nil)
    }
}
