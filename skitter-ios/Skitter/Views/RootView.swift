import SwiftUI

struct RootView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @Environment(\.colorScheme) private var colorScheme

    private var loadingGradient: [Color] {
        if colorScheme == .dark {
            return [
                Color(red: 0.08, green: 0.11, blue: 0.16),
                Color(red: 0.10, green: 0.18, blue: 0.27),
                Color(red: 0.14, green: 0.11, blue: 0.20),
            ]
        }
        return [
            Color(red: 0.93, green: 0.95, blue: 0.98),
            Color(red: 0.86, green: 0.91, blue: 0.97),
        ]
    }

    private var loadingTextColor: Color {
        colorScheme == .dark ? .white : .primary
    }

    var body: some View {
        Group {
            switch model.authenticationState {
            case .loading:
                ZStack {
                    LinearGradient(
                        colors: loadingGradient,
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
                            .foregroundStyle(loadingTextColor)
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
