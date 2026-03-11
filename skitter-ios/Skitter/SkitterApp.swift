import SwiftUI

@main
struct SkitterApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    @StateObject private var settings: SettingsStore
    @StateObject private var model: AppModel

    init() {
        let settingsStore = SettingsStore()
        _settings = StateObject(wrappedValue: settingsStore)
        _model = StateObject(
            wrappedValue: AppModel(
                settings: settingsStore,
                apiClient: APIClient(),
                notificationManager: .shared
            )
        )
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: model, settings: settings)
                .task {
                    await model.start()
                }
                .onChange(of: scenePhase) { _, newValue in
                    model.setScenePhase(newValue)
                }
        }
    }
}
