import SwiftUI

struct AboutView: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "bolt.circle")
                .font(.system(size: 42))
                .foregroundStyle(Color.accentColor)
            Text("Skitter Menu Bar")
                .font(.title3.weight(.semibold))
            Text("Native macOS menu bar companion for Skitter API")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text("MVP")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(24)
        .frame(width: 360)
    }
}
