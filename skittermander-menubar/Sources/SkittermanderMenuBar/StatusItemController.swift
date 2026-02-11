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
        title.image = symbolImage("bolt.circle.fill")
        statusMenu.addItem(title)
        statusMenu.addItem(.separator())

        statusMenu.addItem(disabledInfoItem(
            icon: "waveform.path.ecg",
            label: "Health",
            value: state.health.label.capitalized,
            valueColor: healthValueColor
        ))
        statusMenu.addItem(disabledInfoItem(
            icon: "brain.head.profile",
            label: "Activity",
            value: state.activity.label.capitalized,
            valueColor: activityValueColor
        ))
        statusMenu.addItem(disabledInfoItem(icon: "cpu", label: "Model", value: state.modelName))
        statusMenu.addItem(disabledInfoItem(icon: "text.word.spacing", label: "Context", value: "\(state.contextTokens) tokens"))
        statusMenu.addItem(disabledInfoItem(icon: "dollarsign.circle", label: "Session cost", value: "$\(String(format: "%.2f", state.sessionCost))"))
        if let sessionID = state.sessionID, !sessionID.isEmpty {
            statusMenu.addItem(disabledInfoItem(icon: "number.circle", label: "Session", value: sessionID))
        }
        if !state.pendingToolApprovals.isEmpty {
            statusMenu.addItem(disabledInfoItem(
                icon: "checkmark.shield",
                label: "Approvals",
                value: "\(state.pendingToolApprovals.count) pending",
                valueColor: .systemOrange
            ))
        }
        if state.hasUnreadMessages {
            statusMenu.addItem(disabledInfoItem(
                icon: "envelope.badge",
                label: "Unread",
                value: "\(state.unreadMessageCount)",
                valueColor: .systemBlue
            ))
        }

        statusMenu.addItem(.separator())
        statusMenu.addItem(actionItem(title: "Open Chat", icon: "bubble.left.and.bubble.right", action: #selector(openChatFromMenu)))
        statusMenu.addItem(actionItem(title: "Refresh", icon: "arrow.clockwise", action: #selector(refreshNowFromMenu)))
        statusMenu.addItem(actionItem(title: "Settings…", icon: "gearshape", action: #selector(openSettingsFromMenu)))
        statusMenu.addItem(actionItem(title: "About…", icon: "info.circle", action: #selector(openAboutFromMenu)))
        statusMenu.addItem(.separator())
        statusMenu.addItem(actionItem(title: "Quit", icon: "power", action: #selector(quitFromMenu)))
    }

    private var healthValueColor: NSColor {
        switch state.health {
        case .checking:
            return .systemOrange
        case .healthy:
            return .systemGreen
        case .error:
            return .systemRed
        }
    }

    private var activityValueColor: NSColor {
        switch state.activity {
        case .idle:
            return .secondaryLabelColor
        case .thinking:
            return .systemBlue
        case .activeTasks:
            return .systemOrange
        }
    }

    private func disabledInfoItem(icon: String, label: String, value: String, valueColor: NSColor = .secondaryLabelColor) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.attributedTitle = attributedInfoTitle(label: label, value: value, valueColor: valueColor)
        item.image = symbolImage(icon)
        item.isEnabled = false
        return item
    }

    private func actionItem(title: String, icon: String, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.image = symbolImage(icon)
        item.target = self
        item.isEnabled = true
        return item
    }

    private func symbolImage(_ name: String) -> NSImage? {
        let config = NSImage.SymbolConfiguration(pointSize: 13, weight: .medium)
        return NSImage(systemSymbolName: name, accessibilityDescription: nil)?
            .withSymbolConfiguration(config)
    }

    private func attributedInfoTitle(label: String, value: String, valueColor: NSColor) -> NSAttributedString {
        let text = NSMutableAttributedString()
        text.append(
            NSAttributedString(
                string: "\(label): ",
                attributes: [
                    .foregroundColor: NSColor.secondaryLabelColor,
                    .font: NSFont.systemFont(ofSize: 13, weight: .regular),
                ]
            )
        )
        text.append(
            NSAttributedString(
                string: value,
                attributes: [
                    .foregroundColor: valueColor,
                    .font: NSFont.systemFont(ofSize: 13, weight: .semibold),
                ]
            )
        )
        return text
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
    private func refreshNowFromMenu() {
        Task { @MainActor in
            await state.refreshStatus()
        }
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
