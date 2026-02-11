import AppKit
import Foundation

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let statusItem: NSStatusItem
    private let state: AppState
    private let chatWindowController: ChatWindowController
    private let openSettings: () -> Void
    private let openAbout: () -> Void
    private let statusMenu = NSMenu()
    private let unreadBadgeView = NSView(frame: .zero)
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
        configureUnreadBadge(for: button)
    }

    private func configureUnreadBadge(for button: NSStatusBarButton) {
        unreadBadgeView.translatesAutoresizingMaskIntoConstraints = false
        unreadBadgeView.wantsLayer = true
        unreadBadgeView.layer?.backgroundColor = NSColor.systemRed.cgColor
        unreadBadgeView.layer?.cornerRadius = 4
        unreadBadgeView.layer?.borderWidth = 1
        unreadBadgeView.layer?.borderColor = NSColor.windowBackgroundColor.cgColor
        unreadBadgeView.isHidden = true
        button.addSubview(unreadBadgeView)
        NSLayoutConstraint.activate([
            unreadBadgeView.widthAnchor.constraint(equalToConstant: 8),
            unreadBadgeView.heightAnchor.constraint(equalToConstant: 8),
            unreadBadgeView.trailingAnchor.constraint(equalTo: button.trailingAnchor, constant: -2),
            unreadBadgeView.topAnchor.constraint(equalTo: button.topAnchor, constant: 2),
        ])
    }

    @objc
    private func handleClick(_ sender: Any?) {
        guard let event = NSApp.currentEvent else {
            chatWindowController.toggle(relativeTo: statusItem.button)
            return
        }

        switch event.type {
        case .rightMouseUp:
            chatWindowController.close()
            showStatusMenu(with: event)
        default:
            chatWindowController.toggle(relativeTo: statusItem.button)
        }
    }

    private func showStatusMenu(with event: NSEvent) {
        guard let button = statusItem.button else { return }
        _ = event
        rebuildStatusMenu()
        statusItem.menu = statusMenu
        button.performClick(nil)
    }

    private func rebuildStatusMenu() {
        statusMenu.removeAllItems()
        statusMenu.autoenablesItems = false
        statusMenu.delegate = self

        let title = NSMenuItem(title: "Skittermander", action: nil, keyEquivalent: "")
        title.isEnabled = false
        statusMenu.addItem(title)
        statusMenu.addItem(.separator())

        statusMenu.addItem(disabledInfoItem(label: "Status", value: "\(state.health.label), \(state.activity.label)"))
        statusMenu.addItem(disabledInfoItem(label: "Model", value: state.modelName))
        statusMenu.addItem(disabledInfoItem(label: "Context", value: "\(state.contextTokens) tokens"))
        statusMenu.addItem(disabledInfoItem(label: "Session cost", value: "$\(String(format: "%.2f", state.sessionCost))"))
        if let sessionID = state.sessionID, !sessionID.isEmpty {
            statusMenu.addItem(disabledInfoItem(label: "Session", value: sessionID))
        }
        if !state.pendingToolApprovals.isEmpty {
            statusMenu.addItem(disabledInfoItem(label: "Approvals", value: "\(state.pendingToolApprovals.count) pending"))
        }

        statusMenu.addItem(.separator())
        statusMenu.addItem(actionItem(title: "Open Chat", action: #selector(openChatFromMenu)))
        statusMenu.addItem(actionItem(title: "Settings…", action: #selector(openSettingsFromMenu)))
        statusMenu.addItem(actionItem(title: "About…", action: #selector(openAboutFromMenu)))
        statusMenu.addItem(.separator())
        statusMenu.addItem(actionItem(title: "Quit", action: #selector(quitFromMenu)))
    }

    private func disabledInfoItem(label: String, value: String) -> NSMenuItem {
        let item = NSMenuItem(title: "\(label): \(value)", action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    private func actionItem(title: String, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        item.isEnabled = true
        return item
    }

    @objc
    private func openChatFromMenu() {
        chatWindowController.toggle(relativeTo: statusItem.button)
    }

    @objc
    private func openSettingsFromMenu() {
        openSettings()
    }

    @objc
    private func openAboutFromMenu() {
        openAbout()
    }

    @objc
    private func quitFromMenu() {
        NSApp.terminate(nil)
    }

    func menuDidClose(_ menu: NSMenu) {
        if menu === statusMenu {
            statusItem.menu = nil
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
        if state.hasUnreadMessages {
            unreadBadgeView.isHidden = false
            button.toolTip = "\(state.health.label), \(state.activity.label) · \(state.unreadMessageCount) unread"
        } else {
            unreadBadgeView.isHidden = true
            button.toolTip = "\(state.health.label), \(state.activity.label)"
        }
    }
}
