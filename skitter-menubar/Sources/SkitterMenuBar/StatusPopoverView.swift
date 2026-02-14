import SwiftUI

struct StatusPopoverView: View {
    @ObservedObject var state: AppState
    var openSettings: () -> Void
    var openAbout: () -> Void
    var quitApp: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Skitter")
                .font(.headline)

            VStack(alignment: .leading, spacing: 6) {
                Text("Status: \(state.health.label), \(state.activity.label)")
                    .font(.subheadline)
                Text("Current session cost: $\(String(format: "%.2f", state.sessionCost))")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text("Context: \(state.contextTokens) tokens")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ProgressView(value: max(0, min(1, state.contextProgress)))
                    .progressViewStyle(.linear)
            }

            Divider()

            HStack(spacing: 10) {
                Button("Settings", action: openSettings)
                    .buttonStyle(.bordered)
                Button("About", action: openAbout)
                    .buttonStyle(.bordered)
                Spacer()
                Button("Quit", action: quitApp)
                    .buttonStyle(.borderedProminent)
                    .tint(.red.opacity(0.8))
            }
        }
        .padding(16)
        .frame(width: 320)
        .background(.ultraThinMaterial)
        .preferredColorScheme(.light)
    }
}
