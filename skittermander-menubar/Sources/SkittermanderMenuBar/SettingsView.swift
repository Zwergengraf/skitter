import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings: SettingsStore
    var onApply: () -> Void

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
            }

            Spacer(minLength: 8)

            HStack {
                Spacer()
                Button("Apply & Reconnect", action: onApply)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(minWidth: 560, minHeight: 280)
    }
}
