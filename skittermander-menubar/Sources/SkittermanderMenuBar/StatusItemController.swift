import AppKit
import Foundation
import SwiftUI

@MainActor
final class StatusItemController: NSObject {
    private let statusItem: NSStatusItem
    private let state: AppState
    private let chatWindowController: ChatWindowController
    private let openSettings: () -> Void
    private let openAbout: () -> Void
    private let statusPopover = NSPopover()
    private var refreshTimer: Timer?

    init(
        state: AppState,
        chatWindowController: ChatWindowController,
        openSettings: @escaping () -> Void,
        openAbout: @escaping () -> Void
    ) {
        self.state = state
        self.chatWindowController = chatWindowController
        self.openSettings = openSettings
        self.openAbout = openAbout
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        configureButton()
        configurePopover()
        refreshAppearance()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.refreshAppearance()
            }
        }
    }

    deinit {
        refreshTimer?.invalidate()
    }

    private func configureButton() {
        guard let button = statusItem.button else { return }
        button.target = self
        button.action = #selector(handleClick(_:))
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        button.imagePosition = .imageOnly
        button.toolTip = "Skittermander"
    }

    @objc
    private func handleClick(_ sender: Any?) {
        guard let event = NSApp.currentEvent else {
            statusPopover.performClose(nil)
            chatWindowController.toggle(relativeTo: statusItem.button)
            return
        }

        switch event.type {
        case .rightMouseUp:
            chatWindowController.close()
            toggleStatusPopover()
        default:
            statusPopover.performClose(nil)
            chatWindowController.toggle(relativeTo: statusItem.button)
        }
    }

    private func configurePopover() {
        let view = StatusPopoverView(
            state: state,
            openSettings: { [weak self] in
                self?.openSettings()
                self?.statusPopover.performClose(nil)
            },
            openAbout: { [weak self] in
                self?.openAbout()
                self?.statusPopover.performClose(nil)
            },
            quitApp: {
                NSApp.terminate(nil)
            }
        )
        let host = NSHostingController(rootView: view)
        statusPopover.contentViewController = host
        statusPopover.behavior = .transient
        statusPopover.animates = true
    }

    private func toggleStatusPopover() {
        guard let button = statusItem.button else { return }
        if statusPopover.isShown {
            statusPopover.performClose(nil)
            return
        }
        NSApp.activate(ignoringOtherApps: true)
        statusPopover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        statusPopover.contentViewController?.view.window?.makeKey()
        DispatchQueue.main.async { [weak self] in
            self?.statusPopover.contentViewController?.view.window?.makeKey()
        }
    }

    private func refreshAppearance() {
        guard let button = statusItem.button else { return }

        let symbolName: String

        switch state.health {
        case .checking:
            symbolName = "clock"
        case .healthy:
            switch state.activity {
            case .idle:
                symbolName = "checkmark.circle"
            case .thinking:
                symbolName = "ellipsis.bubble"
            case .activeTasks:
                symbolName = "bolt.circle"
            }
        case .error:
            symbolName = "exclamationmark.triangle"
        }

        button.image = NSImage(systemSymbolName: symbolName, accessibilityDescription: "Skittermander status")
        button.image?.isTemplate = true
        button.contentTintColor = nil
        button.toolTip = "\(state.health.label), \(state.activity.label)"
    }
}
