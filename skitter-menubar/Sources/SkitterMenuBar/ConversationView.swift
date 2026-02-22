import SwiftUI

struct ConversationView: View {
    @ObservedObject var state: AppState

    private var statusLine: String {
        if !state.conversationStatusText.isEmpty {
            return state.conversationStatusText
        }
        if state.isConversationStarting {
            return "Starting local Whisper…"
        }
        if state.isConversationListening {
            return "Listening…"
        }
        return "Paused"
    }

    private var responseText: String {
        let text = state.conversationResponseText.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            return "Speak to send a message to the active session."
        }
        return text
    }

    private var statusTint: Color {
        if state.isConversationTTSPlaying { return Color(red: 0.20, green: 0.72, blue: 0.98) }
        if state.isConversationAwaitingReply { return Color(red: 0.98, green: 0.70, blue: 0.24) }
        if state.isConversationListening { return Color(red: 0.25, green: 0.78, blue: 0.56) }
        if state.isConversationStarting { return Color(red: 0.80, green: 0.54, blue: 0.98) }
        return Color.secondary
    }

    var body: some View {
        ZStack {
            BackdropBlurView(material: .hudWindow, blendingMode: .behindWindow, emphasized: true)
                .ignoresSafeArea()

            LinearGradient(
                colors: [
                    Color(red: 0.06, green: 0.09, blue: 0.16).opacity(0.54),
                    Color(red: 0.05, green: 0.13, blue: 0.20).opacity(0.46),
                    Color(red: 0.09, green: 0.08, blue: 0.15).opacity(0.54),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            RadialGradient(
                colors: [statusTint.opacity(0.30), .clear],
                center: .center,
                startRadius: 20,
                endRadius: 280
            )
            .blendMode(.plusLighter)
            .offset(y: -28)

            VStack(spacing: 16) {
                Text("Skitter Voice")
                    .font(.system(size: 18, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.94))
                    .frame(maxWidth: .infinity, alignment: .center)

                VoiceOrbView(
                    ttsLevel: state.conversationTTSLevel,
                    isSpeaking: state.isConversationTTSPlaying,
                    isListening: state.isConversationListening,
                    isWaiting: state.isConversationAwaitingReply || state.isConversationStarting
                )
                .frame(width: 308, height: 308)
                .padding(.top, 2)

                Button(state.isConversationListening || state.isConversationStarting ? "Stop" : "Start") {
                    Task { await state.toggleConversationListening() }
                }
                .buttonStyle(.borderedProminent)
                .tint(state.isConversationListening ? .red.opacity(0.85) : statusTint.opacity(0.85))

                Text(statusLine)
                    .font(.system(size: 13, weight: .medium, design: .rounded))
                    .foregroundStyle(statusTint.opacity(0.95))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(.thinMaterial, in: Capsule())

                transcriptSlot

                ScrollView {
                    Text(responseText)
                        .font(.system(size: 15, weight: .regular, design: .rounded))
                        .foregroundStyle(.white.opacity(0.92))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxWidth: .infinity, minHeight: 110, maxHeight: 190, alignment: .topLeading)
                .padding(14)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(.white.opacity(0.12), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.30), radius: 20, x: 0, y: 10)

                if let banner = state.errorBanner, !banner.isEmpty {
                    Text(banner)
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(Color(red: 1.0, green: 0.66, blue: 0.66))
                        .padding(.horizontal, 10)
                        .lineLimit(3)
                }
            }
            .padding(.top, 34)
            .padding(.horizontal, 20)
            .padding(.bottom, 20)
        }
        .frame(minWidth: 460, minHeight: 660)
    }

    @ViewBuilder
    private var transcriptSlot: some View {
        let text = state.conversationTranscriptText.trimmingCharacters(in: .whitespacesAndNewlines)
        Group {
            if text.isEmpty {
                Color.clear
            } else {
                Text("Heard: \(text)")
                    .font(.system(size: 12, weight: .regular, design: .rounded))
                    .foregroundStyle(.white.opacity(0.70))
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 32)
    }
}

private struct VoiceOrbView: View {
    let ttsLevel: Double
    let isSpeaking: Bool
    let isListening: Bool
    let isWaiting: Bool

    @State private var breathe = false
    @State private var rotate = false

    private var ringTint: Color {
        if isSpeaking { return Color(red: 0.24, green: 0.79, blue: 1.0) }
        if isWaiting { return Color(red: 0.97, green: 0.73, blue: 0.35) }
        if isListening { return Color(red: 0.32, green: 0.91, blue: 0.63) }
        return Color.white.opacity(0.5)
    }

    private var coreScale: CGFloat {
        if isSpeaking {
            return 1 + CGFloat(0.08 + (ttsLevel * 0.16))
        }
        if isListening {
            return breathe ? 1.04 : 0.98
        }
        if isWaiting {
            return breathe ? 1.02 : 0.99
        }
        return 1
    }

    private var iconName: String {
        if isSpeaking { return "speaker.wave.3.fill" }
        if isWaiting { return "ellipsis" }
        if isListening { return "waveform" }
        return "pause.fill"
    }

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { idx in
                let size = 170.0 + Double(idx * 32)
                Circle()
                    .stroke(
                        LinearGradient(
                            colors: [ringTint.opacity(0.18 + Double(idx) * 0.08), .white.opacity(0.04)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: idx == 0 ? 2.3 : 1.4
                    )
                    .frame(width: size, height: size)
                    .scaleEffect(
                        isSpeaking
                            ? 1 + CGFloat(ttsLevel * (0.15 + Double(idx) * 0.04))
                            : (breathe ? 1.015 + CGFloat(idx) * 0.01 : 0.99)
                    )
                    .rotationEffect(.degrees((rotate ? 360 : 0) * (idx % 2 == 0 ? 1 : -1)))
                    .animation(.easeInOut(duration: 0.18), value: ttsLevel)
                    .animation(.easeInOut(duration: 2.2), value: breathe)
                    .animation(.linear(duration: 18).repeatForever(autoreverses: false), value: rotate)
            }

            Circle()
                .fill(
                    RadialGradient(
                        colors: [ringTint.opacity(0.42), ringTint.opacity(0.18), .clear],
                        center: .center,
                        startRadius: 6,
                        endRadius: 130
                    )
                )
                .blur(radius: 10)

            Circle()
                .fill(
                    LinearGradient(
                        colors: [Color.white.opacity(0.90), ringTint.opacity(0.88), Color.black.opacity(0.18)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 95, height: 95)
                .scaleEffect(coreScale)
                .shadow(color: ringTint.opacity(0.42), radius: 20, x: 0, y: 9)
                .animation(.easeInOut(duration: 0.16), value: ttsLevel)
                .animation(.easeInOut(duration: 2.1), value: breathe)

            if isSpeaking {
                TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
                    let t = timeline.date.timeIntervalSinceReferenceDate
                    HStack(spacing: 4) {
                        ForEach(0..<5, id: \.self) { idx in
                            let wave = abs(sin(t * 6 + Double(idx) * 0.75))
                            let dynamic = max(0.16, ttsLevel) * wave
                            Capsule(style: .continuous)
                                .fill(Color.white.opacity(0.90))
                                .frame(width: 4.5, height: 10 + dynamic * 28)
                        }
                    }
                }
            } else {
                Image(systemName: iconName)
                    .font(.system(size: 30, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.black.opacity(0.58))
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) {
                breathe.toggle()
            }
            withAnimation(.linear(duration: 18).repeatForever(autoreverses: false)) {
                rotate.toggle()
            }
        }
    }
}
