import SwiftUI

struct RootView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore

    var body: some View {
        Group {
            switch model.authenticationState {
            case .loading:
                ZStack {
                    LinearGradient(
                        colors: [
                            Color(red: 0.93, green: 0.95, blue: 0.98),
                            Color(red: 0.86, green: 0.91, blue: 0.97),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    .ignoresSafeArea()

                    VStack(spacing: 16) {
                        ProgressView()
                            .progressViewStyle(.circular)
                            .controlSize(.large)
                        Text("Connecting to Skitter")
                            .font(.headline)
                    }
                }
            case .signedOut:
                OnboardingFlowView(model: model, settings: settings)
            case .signedIn:
                MainShellView(model: model, settings: settings, notifications: .shared)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: model.authenticationState)
    }
}
