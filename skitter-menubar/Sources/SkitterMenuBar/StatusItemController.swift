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
        button.toolTip = "Skitter"
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
        statusMenu.minimumWidth = 340

        let title = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        title.view = headerItemView(label: "Skitter", icon: "bolt.circle.fill", iconColor: healthValueColor)
        title.isEnabled = true
        statusMenu.addItem(title)
        statusMenu.addItem(.separator())

        statusMenu.addItem(infoItem(
            icon: "waveform.path.ecg",
            label: "Health",
            value: state.health.label.capitalized,
            valueColor: healthValueColor
        ))
        statusMenu.addItem(infoItem(
            icon: "brain.head.profile",
            label: "Activity",
            value: state.activity.label.capitalized,
            valueColor: activityValueColor
        ))
        statusMenu.addItem(infoItem(icon: "cpu", label: "Model", value: state.modelName))
        statusMenu.addItem(infoItem(icon: "text.word.spacing", label: "Context", value: "\(state.contextTokens) tokens"))
        statusMenu.addItem(infoItem(icon: "dollarsign.circle", label: "Session cost", value: "$\(String(format: "%.2f", state.sessionCost))"))
        if !state.pendingToolApprovals.isEmpty {
            statusMenu.addItem(infoItem(
                icon: "checkmark.shield",
                label: "Approvals",
                value: "\(state.pendingToolApprovals.count) pending",
                valueColor: .systemOrange
            ))
        }
        if state.hasUnreadMessages {
            statusMenu.addItem(infoItem(
                icon: "envelope.badge",
                label: "Unread",
                value: "\(state.unreadMessageCount)",
                valueColor: .systemBlue
            ))
        }

        statusMenu.addItem(.separator())
        statusMenu.addItem(actionItem(title: "Open Chat", icon: "bubble.left.and.bubble.right", action: #selector(openChatFromMenu)))
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

    private func infoItem(
        icon: String,
        label: String,
        value: String,
        valueColor: NSColor = NSColor.labelColor.withAlphaComponent(0.86)
    ) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.view = infoItemView(icon: icon, label: label, value: value, valueColor: valueColor)
        item.isEnabled = true
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

    private func infoItemView(icon: String, label: String, value: String, valueColor: NSColor) -> NSView {
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 340, height: 22))

        let iconView = NSImageView()
        iconView.image = symbolImage(icon)
        iconView.contentTintColor = NSColor.secondaryLabelColor.withAlphaComponent(0.88)
        iconView.translatesAutoresizingMaskIntoConstraints = false
        iconView.setContentHuggingPriority(.required, for: .horizontal)
        iconView.setContentCompressionResistancePriority(.required, for: .horizontal)

        let labelField = NSTextField(labelWithString: label)
        labelField.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        labelField.textColor = NSColor.labelColor.withAlphaComponent(0.84)
        labelField.lineBreakMode = .byTruncatingTail
        labelField.translatesAutoresizingMaskIntoConstraints = false
        labelField.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let valueField = NSTextField(labelWithString: value)
        valueField.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        valueField.textColor = valueColor
        valueField.alignment = .right
        valueField.lineBreakMode = .byTruncatingMiddle
        valueField.translatesAutoresizingMaskIntoConstraints = false
        valueField.setContentCompressionResistancePriority(.required, for: .horizontal)
        valueField.setContentHuggingPriority(.required, for: .horizontal)

        let spacer = NSView()
        spacer.translatesAutoresizingMaskIntoConstraints = false
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        spacer.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let row = NSStackView(views: [iconView, labelField, spacer, valueField])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        row.translatesAutoresizingMaskIntoConstraints = false

        container.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 14),
            row.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -14),
            row.topAnchor.constraint(equalTo: container.topAnchor, constant: 2),
            row.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -2),
            iconView.widthAnchor.constraint(equalToConstant: 15),
            iconView.heightAnchor.constraint(equalToConstant: 15),
            container.heightAnchor.constraint(equalToConstant: 22),
        ])

        return container
    }

    private func headerItemView(label: String, icon: String, iconColor: NSColor) -> NSView {
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 340, height: 28))

        let iconView = NSImageView()
        iconView.image = symbolImage(icon)
        iconView.contentTintColor = iconColor
        iconView.translatesAutoresizingMaskIntoConstraints = false
        iconView.setContentHuggingPriority(.required, for: .horizontal)
        iconView.setContentCompressionResistancePriority(.required, for: .horizontal)

        let labelField = NSTextField(labelWithString: label)
        labelField.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
        labelField.textColor = NSColor.labelColor.withAlphaComponent(0.88)
        labelField.lineBreakMode = .byTruncatingTail
        labelField.translatesAutoresizingMaskIntoConstraints = false

        let row = NSStackView(views: [iconView, labelField])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        row.translatesAutoresizingMaskIntoConstraints = false

        container.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 14),
            row.trailingAnchor.constraint(lessThanOrEqualTo: container.trailingAnchor, constant: -14),
            row.topAnchor.constraint(equalTo: container.topAnchor, constant: 3),
            row.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -3),
            iconView.widthAnchor.constraint(equalToConstant: 16),
            iconView.heightAnchor.constraint(equalToConstant: 16),
            container.heightAnchor.constraint(equalToConstant: 28),
        ])

        return container
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

        button.image = NSImage(systemSymbolName: symbolName, accessibilityDescription: "Skitter status")
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
