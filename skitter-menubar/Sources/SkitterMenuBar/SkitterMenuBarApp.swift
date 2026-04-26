import AppKit
import SwiftUI

@main
struct SkitterMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let settings = SettingsStore()
    private lazy var state = AppState(settings: settings)
    private var statusController: StatusItemController?
    private var chatWindowController: ChatWindowController?
    private var conversationWindowController: ConversationWindowController?
    private var onboardingWindowController: NSWindowController?
    private var settingsWindowController: NSWindowController?
    private var aboutWindowController: NSWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let conversationController = ConversationWindowController(state: state)
        conversationWindowController = conversationController

        let chatController = ChatWindowController(
            state: state,
            openConversation: { [weak conversationController] in
                conversationController?.toggle()
            },
            openSetupWizard: { [weak self] in
                self?.showOnboardingWindow()
            }
        )
        chatWindowController = chatController

        statusController = StatusItemController(
            state: state,
            chatWindowController: chatController,
            openConversation: { [weak conversationController] in
                conversationController?.show()
            },
            openSetupWizard: { [weak self] in self?.showOnboardingWindow() },
            openSettings: { [weak self] in self?.showSettingsWindow() },
            openAbout: { [weak self] in self?.showAboutWindow() }
        )

        state.start()
        if state.shouldShowOnboarding {
            showOnboardingWindow()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        state.stop()
    }

    private func showSettingsWindow() {
        if let window = settingsWindowController?.window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let root = SettingsView(
            settings: settings,
            state: state,
            onApply: { [weak self] in
                Task { @MainActor in
                    await self?.state.reconnect()
                }
            },
            onClose: { [weak self] in
                self?.settingsWindowController?.close()
            }
        )
        let host = NSHostingController(rootView: root)

        let window = NSWindow(contentViewController: host)
        window.title = "Skitter Settings"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.setContentSize(NSSize(width: 760, height: 700))
        window.minSize = NSSize(width: 680, height: 640)
        window.center()

        let controller = NSWindowController(window: window)
        settingsWindowController = controller
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showOnboardingWindow() {
        if let window = onboardingWindowController?.window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let root = OnboardingWizardView(
            settings: settings,
            state: state,
            onClose: { [weak self] in
                self?.onboardingWindowController?.close()
            },
            onFinish: { [weak self] in
                self?.onboardingWindowController?.close()
            }
        )
        let host = NSHostingController(rootView: root)

        let window = NSWindow(contentViewController: host)
        window.title = "Skitter Setup"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.setContentSize(NSSize(width: 720, height: 560))
        window.minSize = NSSize(width: 660, height: 520)
        window.center()

        let controller = NSWindowController(window: window)
        onboardingWindowController = controller
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showAboutWindow() {
        if let window = aboutWindowController?.window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let host = NSHostingController(rootView: AboutView())
        let window = NSWindow(contentViewController: host)
        window.title = "About Skitter"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.setContentSize(NSSize(width: 360, height: 210))
        window.center()

        let controller = NSWindowController(window: window)
        aboutWindowController = controller
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
