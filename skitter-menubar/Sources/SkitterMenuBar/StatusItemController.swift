import AppKit
import Foundation
import SwiftUI

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let statusItem: NSStatusItem
    private let state: AppState
    private let chatWindowController: ChatWindowController
    private let openConversation: () -> Void
    private let openSetupWizard: () -> Void
    private let openSettings: () -> Void
    private let openAbout: () -> Void
    private let statusMenu = NSMenu()
    private let unreadBadgeView = NSView(frame: .zero)
    private var statusIconHostingView: PassthroughHostingView<MenuBarStatusIconView>?
    private var lastStatusIconStyle: MenuBarStatusIconStyle?
    private var refreshTimer: Timer?
    private let statusSymbolPointSize: CGFloat = 19

    init(
        state: AppState,
        chatWindowController: ChatWindowController,
        openConversation: @escaping () -> Void,
        openSetupWizard: @escaping () -> Void,
        openSettings: @escaping () -> Void,
        openAbout: @escaping () -> Void
    ) {
        self.state = state
        self.chatWindowController = chatWindowController
        self.openConversation = openConversation
        self.openSetupWizard = openSetupWizard
        self.openSettings = openSettings
        self.openAbout = openAbout
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
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
        installStatusIcon(on: button)
        button.toolTip = "Skitter"
        configureUnreadBadge(for: button)
    }

    private func installStatusIcon(on button: NSStatusBarButton?) {
        guard let button else { return }

        statusIconHostingView?.removeFromSuperview()
        statusIconHostingView = nil
        button.image = nil

        let style = currentStatusIconStyle()
        let hostingView = PassthroughHostingView(
            rootView: MenuBarStatusIconView(
                style: style,
                pointSize: statusSymbolPointSize
            )
        )
        hostingView.translatesAutoresizingMaskIntoConstraints = false

        button.addSubview(hostingView)
        NSLayoutConstraint.activate([
            hostingView.centerXAnchor.constraint(equalTo: button.centerXAnchor),
            hostingView.centerYAnchor.constraint(equalTo: button.centerYAnchor),
            hostingView.widthAnchor.constraint(equalToConstant: statusSymbolPointSize + 2),
            hostingView.heightAnchor.constraint(equalToConstant: statusSymbolPointSize + 2),
        ])

        statusIconHostingView = hostingView
        lastStatusIconStyle = style
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
            chatWindowController.focusOrShow(relativeTo: statusItem.button)
            return
        }

        switch event.type {
        case .rightMouseUp:
            chatWindowController.close()
            showStatusMenu(with: event)
        default:
            chatWindowController.focusOrShow(relativeTo: statusItem.button)
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
        statusMenu.addItem(actionItem(title: "Open Conversation Mode", icon: "waveform", action: #selector(openConversationFromMenu)))
        statusMenu.addItem(actionItem(title: "Setup Wizard…", icon: "wand.and.stars", action: #selector(openSetupWizardFromMenu)))
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
        chatWindowController.focusOrShow(relativeTo: statusItem.button)
    }

    @objc
    private func openConversationFromMenu() {
        openConversation()
    }

    @objc
    private func openSetupWizardFromMenu() {
        openSetupWizard()
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
        updateStatusIcon(button: button)
        if state.hasUnreadMessages {
            unreadBadgeView.isHidden = false
            button.toolTip = "\(state.health.label), \(state.activity.label) · \(state.unreadMessageCount) unread"
        } else {
            unreadBadgeView.isHidden = true
            button.toolTip = "\(state.health.label), \(state.activity.label)"
        }
    }

    private func updateStatusIcon(button: NSStatusBarButton) {
        if statusIconHostingView == nil {
            installStatusIcon(on: button)
            return
        }

        let style = currentStatusIconStyle()
        guard style != lastStatusIconStyle else { return }
        statusIconHostingView?.rootView = MenuBarStatusIconView(
            style: style,
            pointSize: statusSymbolPointSize
        )
        lastStatusIconStyle = style
    }

    private func currentStatusIconStyle() -> MenuBarStatusIconStyle {
        switch state.health {
        case .error:
            return MenuBarStatusIconStyle(boltTone: .error, isPulsing: false)
        case .checking:
            return MenuBarStatusIconStyle(boltTone: .accent, isPulsing: true)
        case .healthy:
            switch state.activity {
            case .idle:
                return MenuBarStatusIconStyle(boltTone: .primary, isPulsing: false)
            case .thinking, .activeTasks:
                return MenuBarStatusIconStyle(boltTone: .accent, isPulsing: true)
            }
        }
    }
}

private enum MenuBarBoltTone: Equatable {
    case primary
    case accent
    case error
}

private struct MenuBarStatusIconStyle: Equatable {
    let boltTone: MenuBarBoltTone
    let isPulsing: Bool
}

private struct MenuBarStatusIconView: View {
    let style: MenuBarStatusIconStyle
    let pointSize: CGFloat

    private var boltColor: Color {
        switch style.boltTone {
        case .primary:
            return .primary
        case .accent:
            return .accentColor
        case .error:
            return .red
        }
    }

    private var baseIcon: some View {
        Image(systemName: "bolt.circle")
            .font(.system(size: pointSize, weight: .semibold))
            .symbolRenderingMode(.palette)
            .foregroundStyle(boltColor, Color.white.opacity(0.92))
    }

    var body: some View {
        Group {
            if style.isPulsing {
                if #available(macOS 15.0, *) {
                    baseIcon.symbolEffect(.pulse, options: .repeat(.continuous))
                } else {
                    baseIcon.symbolEffect(.pulse)
                }
            } else {
                baseIcon
            }
        }
        .frame(width: pointSize + 1, height: pointSize + 1)
    }
}

private final class PassthroughHostingView<Content: View>: NSHostingView<Content> {
    override func hitTest(_ point: NSPoint) -> NSView? {
        nil
    }
}
