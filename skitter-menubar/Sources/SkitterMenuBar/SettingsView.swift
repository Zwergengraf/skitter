import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings: SettingsStore
    @ObservedObject var state: AppState
    var onApply: () -> Void
    var onClose: () -> Void
    @State private var bootstrapDisplayName: String = ""
    @State private var bootstrapCode: String = ""
    @State private var pairCode: String = ""
    @State private var showLogoutConfirm: Bool = false

    private var isLoggedIn: Bool {
        !state.currentUserID.isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Server Settings")
                .font(.headline)

            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 12) {
                GridRow {
                    Text("API URL")
                        .frame(width: 130, alignment: .leading)
                    TextField("http://localhost:8000", text: $settings.apiURL)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Access Token")
                        .frame(width: 130, alignment: .leading)
                    SecureField("Token from bootstrap/pair flow", text: $settings.apiKey)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Context Target")
                        .frame(width: 130, alignment: .leading)
                    TextField("32000", value: $settings.contextTokenTarget, format: .number)
                        .textFieldStyle(.roundedBorder)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Account")
                    .font(.subheadline.weight(.semibold))
                if isLoggedIn {
                    Text("Connected as \(state.currentUserDisplayName)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Logout") {
                        showLogoutConfirm = true
                    }
                    .buttonStyle(.bordered)
                    .tint(.red)
                    .confirmationDialog(
                        "Log out from this device?",
                        isPresented: $showLogoutConfirm,
                        titleVisibility: .visible
                    ) {
                        Button("Logout", role: .destructive) {
                            Task {
                                await state.logout()
                            }
                        }
                        Button("Cancel", role: .cancel) {}
                    } message: {
                        Text("You will need a pair code or setup code to connect again.")
                    }
                } else {
                    Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 8) {
                        GridRow {
                            Text("Display Name")
                                .frame(width: 130, alignment: .leading)
                            TextField("Your name", text: $bootstrapDisplayName)
                                .textFieldStyle(.roundedBorder)
                        }
                        GridRow {
                            Text("Setup Code")
                                .frame(width: 130, alignment: .leading)
                            SecureField("First-time setup", text: $bootstrapCode)
                                .textFieldStyle(.roundedBorder)
                        }
                        GridRow {
                            Text("")
                                .frame(width: 130, alignment: .leading)
                            HStack {
                                Button("Register & Connect") {
                                    Task {
                                        await state.bootstrapAccount(setupCode: bootstrapCode, displayName: bootstrapDisplayName)
                                    }
                                }
                                .buttonStyle(.bordered)
                                Spacer()
                            }
                        }
                        GridRow {
                            Text("Pair Code")
                                .frame(width: 130, alignment: .leading)
                            TextField("ABCD-1234", text: $pairCode)
                                .textFieldStyle(.roundedBorder)
                        }
                        GridRow {
                            Text("")
                                .frame(width: 130, alignment: .leading)
                            HStack {
                                Button("Pair Existing Account") {
                                    Task {
                                        await state.pairAccount(pairCode: pairCode)
                                    }
                                }
                                .buttonStyle(.bordered)
                                Spacer()
                            }
                        }
                    }
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Speech Recognition")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                }
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
                    GridRow {
                        Text("Language")
                            .frame(width: 130, alignment: .leading)
                        Picker("Language", selection: $settings.speechRecognitionLocaleIdentifier) {
                            ForEach(SettingsStore.speechRecognitionLocaleOptions) { option in
                                Text(option.title).tag(option.id)
                            }
                        }
                        .pickerStyle(.menu)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    GridRow {
                        Text("On-device only")
                            .frame(width: 130, alignment: .leading)
                        Toggle("", isOn: $settings.speechRecognitionRequiresOnDevice)
                            .toggleStyle(.switch)
                    }
                }
                Text("Uses Apple Speech for chat dictation and voice conversation. On-device-only mode may not be available for every language.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Voice Conversation")
                    .font(.subheadline.weight(.semibold))
                HStack {
                    Text("Auto-send silence")
                        .frame(width: 130, alignment: .leading)
                    Stepper(value: $settings.conversationSilenceSeconds, in: 0.6...5.0, step: 0.1) {
                        Text("\(settings.conversationSilenceSeconds, specifier: "%.1f") s")
                            .monospacedDigit()
                    }
                    Spacer()
                }
                Text("After this much silence, speech is sent to the active session automatically.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("OpenAI TTS")
                    .font(.subheadline.weight(.semibold))

                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
                    GridRow {
                        Text("Base URL")
                            .frame(width: 130, alignment: .leading)
                        TextField("https://api.openai.com/v1", text: $settings.openAIBaseURL)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text("API Key")
                            .frame(width: 130, alignment: .leading)
                        SecureField("sk-...", text: $settings.openAIAPIKey)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text("TTS Model")
                            .frame(width: 130, alignment: .leading)
                        TextField("gpt-4o-mini-tts", text: $settings.openAITTSModel)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text("Voice Model")
                            .frame(width: 130, alignment: .leading)
                        TextField("alloy", text: $settings.openAITTSVoice)
                            .textFieldStyle(.roundedBorder)
                    }
                }
                Text("Conversation replies use these settings for OpenAI text-to-speech.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            HStack {
                Spacer()
                Button("Close", action: onClose)
                Button("Save", action: onApply)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(minWidth: 680, minHeight: 640)
    }
}
