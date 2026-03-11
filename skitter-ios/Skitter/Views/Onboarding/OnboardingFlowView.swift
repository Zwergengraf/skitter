import SwiftUI

private enum OnboardingAuthMode: String, CaseIterable, Identifiable {
    case setup
    case pair
    case token

    var id: String { rawValue }

    var title: String {
        switch self {
        case .setup:
            return "Setup Code"
        case .pair:
            return "Pair Code"
        case .token:
            return "Access Token"
        }
    }

    var subtitle: String {
        switch self {
        case .setup:
            return "Create and connect the first account."
        case .pair:
            return "Attach this device to an existing account."
        case .token:
            return "Paste an existing token for advanced setups."
        }
    }
}

struct OnboardingFlowView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: SettingsStore
    @Environment(\.colorScheme) private var colorScheme

    @State private var authMode: OnboardingAuthMode = .setup
    @State private var displayName: String = ""
    @State private var setupCode: String = ""
    @State private var pairCode: String = ""
    @State private var manualToken: String = ""
    @State private var isTestingConnection = false

    private var backgroundGradient: [Color] {
        if colorScheme == .dark {
            return [
                Color(red: 0.07, green: 0.10, blue: 0.15),
                Color(red: 0.09, green: 0.17, blue: 0.24),
                Color(red: 0.15, green: 0.11, blue: 0.18),
            ]
        }
        return [
            Color(red: 0.95, green: 0.97, blue: 0.99),
            Color(red: 0.88, green: 0.92, blue: 0.97),
            Color(red: 0.97, green: 0.94, blue: 0.90),
        ]
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: backgroundGradient,
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 24) {
                    hero
                    serverCard
                    authCard
                    if let error = model.errorText, !error.isEmpty {
                        errorCard(error)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 28)
                .frame(maxWidth: 720)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 30, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .frame(height: 210)
                    .overlay(
                        LinearGradient(
                            colors: [
                                Color(red: 0.18, green: 0.43, blue: 0.78).opacity(0.28),
                                Color(red: 0.09, green: 0.72, blue: 0.63).opacity(0.18),
                                Color(red: 0.90, green: 0.57, blue: 0.24).opacity(0.18),
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 30, style: .continuous))
                    )

                VStack(alignment: .leading, spacing: 14) {
                    Label("Skitter for iPhone and iPad", systemImage: "ipad.and.iphone")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)

                    Text("Personal AI assistant platform")
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .foregroundStyle(.primary)

                    Text("Connect to your server to get started.")
                        .font(.body)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: 520, alignment: .leading)
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var serverCard: some View {
        card {
            VStack(alignment: .leading, spacing: 14) {
                Text("Server")
                    .font(.title3.weight(.semibold))

                Text("Use the base API URL for your Skitter server. The iOS app speaks to the same endpoints as `skitter-menubar`.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                TextField("http://127.0.0.1:8000", text: $settings.apiURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)

                HStack(spacing: 12) {
                    Button(isTestingConnection ? "Testing..." : "Test Connection") {
                        Task {
                            isTestingConnection = true
                            _ = await model.testServerConnection()
                            isTestingConnection = false
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isTestingConnection)

                    Label(model.health.label, systemImage: statusImage)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var authCard: some View {
        card {
            VStack(alignment: .leading, spacing: 18) {
                Text("Connect This Device")
                    .font(.title3.weight(.semibold))

                Picker("Auth Mode", selection: $authMode) {
                    ForEach(OnboardingAuthMode.allCases) { mode in
                        Text(mode.title).tag(mode)
                    }
                }
                .pickerStyle(.segmented)

                Text(authMode.subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                switch authMode {
                case .setup:
                    VStack(alignment: .leading, spacing: 10) {
                        TextField("Display name", text: $displayName)
                            .textFieldStyle(.roundedBorder)
                        SecureField("Setup code", text: $setupCode)
                            .textFieldStyle(.roundedBorder)
                        Button("Register and Connect") {
                            Task {
                                await model.bootstrapAccount(setupCode: setupCode, displayName: displayName)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                case .pair:
                    VStack(alignment: .leading, spacing: 10) {
                        TextField("ABCD-1234", text: $pairCode)
                            .textFieldStyle(.roundedBorder)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                        Button("Pair Existing Account") {
                            Task {
                                await model.pairAccount(pairCode: pairCode)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                case .token:
                    VStack(alignment: .leading, spacing: 10) {
                        SecureField("Bearer token", text: $manualToken)
                            .textFieldStyle(.roundedBorder)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        Button("Connect With Token") {
                            Task {
                                await model.signInWithToken(manualToken)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            }
        }
    }

    private func errorCard(_ text: String) -> some View {
        card {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Text(text)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
            }
        }
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content()
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(colorScheme == .dark ? Color.white.opacity(0.12) : Color.white.opacity(0.35), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(colorScheme == .dark ? 0.28 : 0.06), radius: 20, x: 0, y: 12)
    }

    private var statusImage: String {
        switch model.health {
        case .checking:
            return "ellipsis.circle"
        case .healthy:
            return "checkmark.circle.fill"
        case .error:
            return "xmark.octagon.fill"
        }
    }
}
