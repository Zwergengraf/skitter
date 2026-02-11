import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings: SettingsStore
    @ObservedObject var state: AppState
    var onApply: () -> Void
    var onDownloadWhisperModel: () -> Void
    var onClose: () -> Void

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
                    Text("API Key")
                        .frame(width: 130, alignment: .leading)
                    SecureField("Required", text: $settings.apiKey)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("User ID")
                        .frame(width: 130, alignment: .leading)
                    TextField("menubar.local", text: $settings.userID)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Context Target")
                        .frame(width: 130, alignment: .leading)
                    TextField("32000", value: $settings.contextTokenTarget, format: .number)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Whisper Model")
                        .frame(width: 130, alignment: .leading)
                    Picker("Whisper Model", selection: $settings.whisperModel) {
                        ForEach(SettingsStore.whisperModelOptions, id: \.self) { model in
                            Text(model).tag(model)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Whisper Model Download")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Button(state.whisperDownloadInProgress ? "Downloading…" : "Download Model") {
                        onDownloadWhisperModel()
                    }
                    .disabled(state.whisperDownloadInProgress)
                }
                if state.whisperDownloadInProgress || state.whisperDownloadProgress > 0 {
                    ProgressView(value: state.whisperDownloadProgress)
                        .progressViewStyle(.linear)
                }
                if !state.whisperDownloadStatusText.isEmpty {
                    Text(state.whisperDownloadStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                } else {
                    Text("Download the selected model before using microphone transcription.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
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
        .frame(minWidth: 620, minHeight: 360)
        .onChange(of: settings.whisperModel) { _, _ in
            state.clearWhisperDownloadStateForModelChange()
        }
    }
}
