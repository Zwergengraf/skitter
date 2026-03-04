import Foundation
import SwiftUI

private enum OnboardingStep: Int, CaseIterable {
    case welcome
    case server
    case auth

    var title: String {
        switch self {
        case .welcome:
            return "Welcome"
        case .server:
            return "Server"
        case .auth:
            return "Sign In"
        }
    }

    var subtitle: String {
        switch self {
        case .welcome:
            return "Connect this device to your Skitter server"
        case .server:
            return "Confirm the API endpoint"
        case .auth:
            return "Choose how to authenticate"
        }
    }
}

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

    var description: String {
        switch self {
        case .setup:
            return "First install. Create and connect an account."
        case .pair:
            return "Connect this device to an existing account."
        case .token:
            return "Paste an existing token manually."
        }
    }

    var icon: String {
        switch self {
        case .setup:
            return "sparkles"
        case .pair:
            return "link"
        case .token:
            return "key.horizontal"
        }
    }
}

struct OnboardingWizardView: View {
    @ObservedObject var settings: SettingsStore
    @ObservedObject var state: AppState
    var onClose: () -> Void
    var onFinish: () -> Void

    @State private var step: OnboardingStep = .welcome
    @State private var authMode: OnboardingAuthMode = .setup
    @State private var setupDisplayName: String = ""
    @State private var setupCode: String = ""
    @State private var pairCode: String = ""
    @State private var token: String = ""
    @State private var isTestingConnection: Bool = false
    @State private var testStatus: String = ""
    @State private var isConnecting: Bool = false
    @State private var localError: String = ""

    private var panelBackground: Color {
        Color(nsColor: .controlBackgroundColor).opacity(0.75)
    }

    private var panelStroke: Color {
        Color(nsColor: .separatorColor).opacity(0.40)
    }

    private var isFinalStep: Bool {
        step == .auth
    }

    private var canContinue: Bool {
        switch step {
        case .welcome:
            return true
        case .server:
            return !settings.apiURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .auth:
            switch authMode {
            case .setup:
                return !setupCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && !setupDisplayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .pair:
                return !pairCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .token:
                return !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
        }
    }

    private var primaryButtonTitle: String {
        if isConnecting {
            return "Connecting…"
        }
        return isFinalStep ? "Connect" : "Next"
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
            if !localError.isEmpty {
                Divider()
                Text(localError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 10)
                    .background(Color.red.opacity(0.08))
            }
            Divider()
            footer
        }
        .padding(0)
        .background(
            ZStack {
                BackdropBlurView(material: .hudWindow, blendingMode: .behindWindow, emphasized: true)
                Color(nsColor: .windowBackgroundColor).opacity(0.72)
            }
        )
        .onAppear {
            setupDisplayName = setupDisplayName.isEmpty ? defaultDisplayName() : setupDisplayName
        }
    }

    @ViewBuilder
    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "bolt.circle.fill")
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Skitter Setup")
                        .font(.title3.weight(.semibold))
                    Text(step.subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            HStack(spacing: 8) {
                ForEach(OnboardingStep.allCases, id: \.rawValue) { item in
                    stepChip(item)
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
    }

    @ViewBuilder
    private var content: some View {
        Group {
            switch step {
            case .welcome:
                welcomeStep
            case .server:
                serverStep
            case .auth:
                authStep
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(18)
    }

    @ViewBuilder
    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("This wizard sets up your local menubar client in three quick steps.")
                .font(.body)
            featureRow(icon: "network", title: "Connect", text: "Point the app to your Skitter API server.")
            featureRow(icon: "person.crop.circle.badge.checkmark", title: "Authenticate", text: "Use setup code, pair code, or existing token.")
            featureRow(icon: "bubble.left.and.bubble.right", title: "Start chatting", text: "Open chat immediately after connection succeeds.")
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(panelBackground)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(panelStroke, lineWidth: 1))
        )
    }

    @ViewBuilder
    private var serverStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Server URL")
                .font(.headline)
            Text("Use the base API URL, for example `http://localhost:8000` or `https://your-server.example`.")
                .font(.caption)
                .foregroundStyle(.secondary)

            TextField("http://localhost:8000", text: $settings.apiURL)
                .textFieldStyle(.roundedBorder)

            HStack(spacing: 8) {
                Button(isTestingConnection ? "Testing…" : "Test Connection") {
                    Task {
                        localError = ""
                        testStatus = ""
                        isTestingConnection = true
                        let ok = await state.testServerConnection()
                        isTestingConnection = false
                        testStatus = ok ? "Server reachable." : (state.errorBanner ?? "Could not reach server.")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isTestingConnection)

                if !testStatus.isEmpty {
                    Text(testStatus)
                        .font(.caption)
                        .foregroundStyle(testStatus == "Server reachable." ? .green : .secondary)
                        .lineLimit(2)
                }
                Spacer()
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(panelBackground)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(panelStroke, lineWidth: 1))
        )
    }

    @ViewBuilder
    private var authStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Authentication")
                .font(.headline)

            HStack(spacing: 10) {
                ForEach(OnboardingAuthMode.allCases) { mode in
                    Button {
                        authMode = mode
                        localError = ""
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Label(mode.title, systemImage: mode.icon)
                                .font(.subheadline.weight(.semibold))
                            Text(mode.description)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(authMode == mode ? Color.accentColor.opacity(0.18) : panelBackground)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(authMode == mode ? Color.accentColor.opacity(0.70) : panelStroke, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }

            switch authMode {
            case .setup:
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Text("Display Name")
                            .foregroundStyle(.secondary)
                            .frame(width: 120, alignment: .leading)
                        TextField("Your name", text: $setupDisplayName)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text("Setup Code")
                            .foregroundStyle(.secondary)
                            .frame(width: 120, alignment: .leading)
                        SecureField("First-time setup code", text: $setupCode)
                            .textFieldStyle(.roundedBorder)
                    }
                }
            case .pair:
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Text("Pair Code")
                            .foregroundStyle(.secondary)
                            .frame(width: 120, alignment: .leading)
                        TextField("ABCD-1234", text: $pairCode)
                            .textFieldStyle(.roundedBorder)
                    }
                }
            case .token:
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Text("Access Token")
                            .foregroundStyle(.secondary)
                            .frame(width: 120, alignment: .leading)
                        SecureField("Paste token", text: $token)
                            .textFieldStyle(.roundedBorder)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(panelBackground)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(panelStroke, lineWidth: 1))
        )
    }

    @ViewBuilder
    private var footer: some View {
        HStack(spacing: 10) {
            Button("Cancel") {
                onClose()
            }
            .buttonStyle(.bordered)

            Button("Back") {
                moveBack()
            }
            .buttonStyle(.bordered)
            .disabled(step == .welcome || isConnecting)

            Spacer()

            Button(primaryButtonTitle) {
                Task { await advanceOrConnect() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canContinue || isConnecting)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private func stepChip(_ item: OnboardingStep) -> some View {
        let isActive = item == step
        Text(item.title)
            .font(.caption.weight(.semibold))
            .foregroundStyle(isActive ? .white : .secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                Capsule()
                    .fill(isActive ? Color.accentColor : Color.secondary.opacity(0.16))
            )
    }

    @ViewBuilder
    private func featureRow(icon: String, title: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.headline)
                .frame(width: 18)
                .foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func moveBack() {
        guard let previous = OnboardingStep(rawValue: step.rawValue - 1) else { return }
        step = previous
        localError = ""
    }

    private func advance() {
        guard let next = OnboardingStep(rawValue: step.rawValue + 1) else { return }
        step = next
        localError = ""
    }

    private func advanceOrConnect() async {
        if !isFinalStep {
            advance()
            return
        }
        await connect()
    }

    private func connect() async {
        localError = ""
        testStatus = ""
        isConnecting = true
        state.dismissErrorBanner()

        switch authMode {
        case .setup:
            await state.bootstrapAccount(setupCode: setupCode, displayName: setupDisplayName)
        case .pair:
            await state.pairAccount(pairCode: pairCode)
        case .token:
            let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                localError = "Access token is required."
                isConnecting = false
                return
            }
            settings.apiKey = trimmed
            await state.reconnect()
        }

        isConnecting = false

        if state.hasWorkingConnection && !state.currentUserID.isEmpty {
            onFinish()
            return
        }
        localError = state.errorBanner ?? "Connection failed. Check your values and try again."
    }

    private func defaultDisplayName() -> String {
        Host.current().localizedName?.trimmingCharacters(in: .whitespacesAndNewlines)
            .nonEmptyOrNil
            ?? "Skitter User"
    }
}

private extension String {
    var nonEmptyOrNil: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
