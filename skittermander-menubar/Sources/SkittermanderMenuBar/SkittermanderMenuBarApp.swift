import AppKit
import SwiftUI

@main
struct SkittermanderMenuBarApp: App {
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
    private var settingsWindowController: NSWindowController?
    private var aboutWindowController: NSWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let chatController = ChatWindowController(state: state)
        chatWindowController = chatController

        statusController = StatusItemController(
            state: state,
            chatWindowController: chatController,
            openSettings: { [weak self] in self?.showSettingsWindow() },
            openAbout: { [weak self] in self?.showAboutWindow() }
        )

        state.start()
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

        let root = SettingsView(settings: settings, onApply: { [weak self] in
            Task { @MainActor in
                await self?.state.reconnect()
            }
        })
        let host = NSHostingController(rootView: root)

        let window = NSWindow(contentViewController: host)
        window.title = "Skittermander Settings"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.setContentSize(NSSize(width: 620, height: 320))
        window.minSize = NSSize(width: 560, height: 280)
        window.center()

        let controller = NSWindowController(window: window)
        settingsWindowController = controller
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
        window.title = "About Skittermander"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.setContentSize(NSSize(width: 360, height: 210))
        window.center()

        let controller = NSWindowController(window: window)
        aboutWindowController = controller
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
