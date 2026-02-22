import AppKit
import Combine
import SwiftUI

private final class ChatPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

@MainActor
final class ChatWindowController: NSObject, NSWindowDelegate {
    private let state: AppState
    private let hostController: NSHostingController<ChatView>
    private var windowController: NSWindowController?
    private var keyMonitor: Any?
    private var localClickMonitor: Any?
    private var globalClickMonitor: Any?
    private var pinObserver: AnyCancellable?

    init(state: AppState, openConversation: @escaping () -> Void) {
        self.state = state
        self.hostController = NSHostingController(rootView: ChatView(state: state, onOpenConversation: openConversation))
        super.init()
        pinObserver = state.$isChatPinned
            .receive(on: RunLoop.main)
            .sink { [weak self] pinned in
                self?.applyPinState(pinned)
            }
    }

    func toggle(relativeTo button: NSStatusBarButton?) {
        focusOrShow(relativeTo: button)
    }

    func focusOrShow(relativeTo button: NSStatusBarButton?) {
        if let window = windowController?.window, window.isVisible {
            applyPinState(state.isChatPinned)
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            state.setChatWindowVisible(true)
            state.markChatOpened()
            return
        }
        show(relativeTo: button)
    }

    func close() {
        state.setChatWindowVisible(false)
        removeMonitors()
        windowController?.window?.orderOut(nil)
    }

    private func show(relativeTo button: NSStatusBarButton?) {
        let controller = ensureWindowController()
        guard let window = controller.window else { return }

        position(window: window, relativeTo: button)
        controller.showWindow(nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        state.setChatWindowVisible(true)
        state.markChatOpened()
        installMonitors()

        Task { @MainActor in
            _ = try? await state.ensureSession(forceNew: false, syncWithServer: true)
            state.markChatOpened()
        }
    }

    func windowWillClose(_ notification: Notification) {
        state.setChatWindowVisible(false)
        removeMonitors()
    }

    func windowDidResignKey(_ notification: Notification) {
        guard !state.isChatPinned else { return }
        if windowController?.window?.isVisible == true {
            close()
        }
    }

    private func ensureWindowController() -> NSWindowController {
        if let windowController {
            return windowController
        }

        let window = ChatPanel(
            contentRect: NSRect(x: 0, y: 0, width: 540, height: 660),
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.contentViewController = hostController
        window.title = "Skitter Chat"
        window.setContentSize(NSSize(width: 540, height: 660))
        window.minSize = NSSize(width: 500, height: 620)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.alphaValue = 0.985
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.hidesOnDeactivate = !state.isChatPinned
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        window.delegate = self
        applyRoundedCorners(to: window)

        let controller = NSWindowController(window: window)
        windowController = controller
        return controller
    }

    private func applyRoundedCorners(to window: NSWindow) {
        guard let content = window.contentViewController?.view else { return }
        content.wantsLayer = true
        content.layer?.cornerRadius = 14
        content.layer?.cornerCurve = .continuous
        content.layer?.masksToBounds = true
    }

    private func applyPinState(_ pinned: Bool) {
        windowController?.window?.hidesOnDeactivate = !pinned
    }

    private func position(window: NSWindow, relativeTo button: NSStatusBarButton?) {
        let size = window.frame.size
        guard
            let button,
            let buttonWindow = button.window
        else {
            window.center()
            return
        }

        let buttonRectInWindow = button.convert(button.bounds, to: nil)
        let buttonRectOnScreen = buttonWindow.convertToScreen(buttonRectInWindow)

        var origin = NSPoint(
            x: buttonRectOnScreen.midX - (size.width / 2),
            y: buttonRectOnScreen.minY - size.height - 8
        )

        let screen = buttonWindow.screen ?? NSScreen.main
        if let visible = screen?.visibleFrame {
            let insetVisible = visible.insetBy(dx: 8, dy: 8)
            origin.x = min(max(origin.x, insetVisible.minX), insetVisible.maxX - size.width)
            origin.y = min(max(origin.y, insetVisible.minY), insetVisible.maxY - size.height)
        }

        window.setFrameOrigin(origin)
    }

    private func installMonitors() {
        removeMonitors()

        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            guard self.windowController?.window?.isVisible == true else { return event }
            if event.keyCode == 53 { // Escape
                self.close()
                return nil
            }
            return event
        }

        localClickMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard let self else { return event }
            guard let window = self.windowController?.window, window.isVisible else { return event }
            guard !self.state.isChatPinned else { return event }
            if event.window !== window {
                self.close()
            }
            return event
        }

        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard !self.state.isChatPinned else { return }
                self.close()
            }
        }
    }

    private func removeMonitors() {
        if let keyMonitor {
            NSEvent.removeMonitor(keyMonitor)
            self.keyMonitor = nil
        }
        if let localClickMonitor {
            NSEvent.removeMonitor(localClickMonitor)
            self.localClickMonitor = nil
        }
        if let globalClickMonitor {
            NSEvent.removeMonitor(globalClickMonitor)
            self.globalClickMonitor = nil
        }
    }
}
