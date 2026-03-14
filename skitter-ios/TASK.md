# Skitter iOS Client Plan

This directory is the starting point for a native iOS client for Skitter.

The goal is not to port the macOS menubar UI directly. The goal is to use the existing `skitter-menubar` feature set as the product reference, then design an iPhone-first experience that feels clean, calm, fast, and modern.

## Reference Inputs

Use these existing files as the main behavioral references while building the iOS client:

- `skitter-menubar/README.md`
- `skitter-menubar/Sources/SkitterMenuBar/AppState.swift`
- `skitter-menubar/Sources/SkitterMenuBar/APIClient.swift`
- `skitter-menubar/Sources/SkitterMenuBar/ChatView.swift`
- `skitter-menubar/Sources/SkitterMenuBar/ConversationView.swift`
- `skitter-menubar/Sources/SkitterMenuBar/SettingsView.swift`
- `skitter-menubar/Sources/SkitterMenuBar/OnboardingWizardView.swift`

## Product Goals

- Make Skitter feel natural on iPhone: full-screen chat, one-handed flows, strong keyboard handling, clear hierarchy.
- Keep the same core power as the menubar app: auth, active-session chat, model switching, tool approvals, commands, and voice.
- Hide technical complexity until it is needed. Status, cost, context, and tool details should be available, but not visually noisy.
- Build a polished UI with soft depth, restrained motion, readable typography, and premium voice interactions.
- Keep the app reliable on mobile networks with good offline, retry, and reconnect behavior.

## Assumptions

- Universal MVP: iPhone and iPad support from the first implementation.
- SwiftUI-native app targeting iOS 17+.
- Same Skitter API surface as `skitter-menubar`.
- Polling and sync remain API-driven for v1, with app-level notification plumbing added immediately.

## Current Feature Parity Targets From `skitter-menubar`

- Server connection and health check
- First-device bootstrap flow
- Pair existing account flow
- Manual access-token sign in
- Resume active session
- Start a new session
- Chat timeline with markdown rendering
- Attachments open/download handling
- Slash-command support
- Model picker
- Context, token, and cost visibility
- Pending tool approval review and approve/deny actions
- Unread/activity indicators
- Voice transcription
- Dedicated voice conversation mode
- TTS playback for conversation replies
- Logout and account state

## Initial Mobile Additions

- Adaptive iPad layout from day one, not a phone-only stretched UI
- Notification permission onboarding
- App badge updates for unread replies and pending approvals
- APNs device-token capture and notification plumbing
- Local notification fallback for new replies while the app is backgrounded or inactive

## UX Direction

- Primary surfaces:
  - Onboarding
  - Chat
  - Voice
  - Details and approvals sheets
  - Settings
- Default view should be the active chat session, not a dashboard.
- Status should be compact and ambient by default, with deeper operational detail moved into sheets.
- Approvals should feel safe and understandable, with clear language, visible consequences, and large tap targets.
- Voice mode should feel premium: large central control, live transcript feedback, subtle haptics, clean motion, obvious start/stop state.

## Task Breakdown

### 1. Foundation

- [x] Create the iOS app target and base project structure in this directory.
- [x] Set up SwiftUI app architecture with a central app state modeled after `AppState.swift`, but adapted for mobile lifecycle and backgrounding.
- [x] Build a shared networking layer for the existing API endpoints used by the menubar client.
- [x] Store auth tokens in Keychain and user preferences in `UserDefaults`.
- [ ] Define a small design system: color tokens, spacing scale, materials, radius scale, typography, and motion rules.
- [x] Add structured error handling for auth failures, network failures, timeout states, and invalid server configuration.
- [x] Build adaptive app navigation for both iPhone and iPad from the start.

### 2. Onboarding And Authentication

- [x] Build a welcome flow with a short explanation of what Skitter is and what users need to connect.
- [x] Add server setup screen with API URL entry, validation, and "Test Connection".
- [x] Add authentication mode chooser:
  - Setup Code
  - Pair Code
  - Existing Access Token
- [x] Implement bootstrap flow with display name + setup code.
- [x] Implement pair flow with pair code entry and success state.
- [x] Implement manual token flow for advanced users.
- [x] Show the connected account identity after auth succeeds.
- [x] Prompt for notifications at the appropriate point in onboarding instead of burying it in settings.
- [x] Add logout flow with confirmation and a clean return to onboarding.

### 3. Chat MVP

- [x] Build a full-screen active-session chat view that resumes the current session on launch.
- [x] Add a prominent "New Session" action.
- [x] Support markdown rendering for assistant messages.
- [x] Add multiline composer with strong keyboard behavior and fast send interaction.
- [x] Add slash-command suggestions while typing `/`.
- [x] Support the menubar command set:
  - `/help`
  - `/new`
  - `/memory_reindex`
  - `/memory_search`
  - `/schedule_list`
  - `/schedule_delete`
  - `/schedule_pause`
  - `/schedule_resume`
  - `/tools`
  - `/model`
  - `/machine`
  - `/pair`
  - `/info`
- [x] Add inline thinking/progress state while the agent is working.
- [x] Add empty, loading, reconnect, and expired-auth states that are readable and actionable.

### 4. Attachments And Message Actions

- [x] Display message attachments clearly inside the conversation thread.
- [x] Add preview/open behavior for common file types.
- [x] Add download/share/export behavior using iOS-native share sheets.
- [x] Add message actions such as copy text and speak response via message long-press, while keeping attachment sharing native.

### 5. Status, Session Details, And Model Controls

- [x] Add a compact session status area showing health, activity, and current model.
- [x] Add a session details sheet for:
  - model picker
  - total tokens
  - context usage
  - session cost
- [x] Preserve the menubar behavior of refreshing model availability from the server.
- [x] Surface unread changes in-app and with app badge support where practical.
- [ ] Make technical stats secondary so the main chat stays visually calm.

### 6. Tool Approvals

- [x] Add inline approval cards in chat when a pending tool run is relevant to the current session.
- [x] Add a dedicated approvals sheet/inbox for reviewing all pending approvals cleanly.
- [x] Show tool name, requester, parameters, secret refs, and created time in a readable mobile layout.
- [x] Implement approve/deny actions with explicit loading and success/error feedback.
- [x] Make approval UI safe for small screens: expandable JSON, clear destructive styling, and no cramped controls.

### 7. Voice Experience

- [x] Add quick voice dictation from the main chat composer.
- [x] Add a dedicated Voice screen inspired by the menubar `ConversationView`, but redesigned for touch-first use.
- [x] Include:
  - large animated central control
  - live transcript preview
  - visible listening / waiting / speaking states
  - response card
  - strong stop/cancel affordances
- [x] Add adjustable silence-to-send behavior.
- [x] Add TTS playback for assistant replies with interrupt/stop control.
- [x] Support a conversation-only model override, matching the existing menubar capability.
- [x] Decide transcription strategy:
  - MVP: use Apple Speech APIs for low-friction mobile voice input
  - Later/privacy mode: evaluate on-device WhisperKit if performance, storage, and battery costs are acceptable

### 8. Settings And Personalization

- [x] Build a settings screen for server config, account info, audio options, and app preferences.
- [x] Add controls for silence threshold, TTS voice selection, and model defaults where appropriate.
- [x] Add an account/device section that can later support pair-code generation.
- [x] Add notification settings, permission status, device token visibility, and badge behavior controls.
- [x] Add support/debug info such as app version, server URL, current user, and session refresh controls.
- [ ] Surface last successful sync / last refresh timestamp in the app UI.
- [ ] Respect Dynamic Type, VoiceOver, reduced motion, and haptic preferences.

### 9. Notifications

- [x] Request notification permissions with clear context about why they matter.
- [x] Capture APNs device tokens and store/report them locally for future backend registration.
- [x] Trigger local notifications for new assistant replies when the app is not active.
- [x] Update the app badge for unread replies and pending approvals.
- [x] Leave the notification layer ready for a future server-side push registration endpoint.

### 10. Visual Polish

- [ ] Establish a sleek visual style based on layered materials, subtle gradients, crisp spacing, and restrained animation.
- [ ] Use motion deliberately for chat send states, reconnect recovery, approval decisions, and voice state changes.
- [ ] Optimize the app for one-handed use and safe-area ergonomics.
- [ ] Validate layouts on smaller phones, larger Pro Max devices, and common iPad sizes.
- [ ] Keep the UI feeling premium without turning it into a dashboard full of metrics.

### 11. Engineering And QA

- [x] Mirror the menubar API usage for these endpoints:
  - `/health`
  - `/v1/auth/bootstrap`
  - `/v1/auth/pair/complete`
  - `/v1/auth/me`
  - `/v1/sessions`
  - `/v1/sessions/{id}`
  - `/v1/sessions/{id}/detail`
  - `/v1/sessions/{id}/model`
  - `/v1/messages`
  - `/v1/models`
  - `/v1/tools`
  - `/v1/commands/execute`
- [x] Preserve active-session reuse semantics from the menubar client.
- [x] Add unit tests for command matching, message formatting, and approval parsing helpers.
- [ ] Add unit tests for API decoding, auth state, and session state transitions.
- [ ] Add UI tests for onboarding, chat send, approvals, and voice-state transitions.
- [ ] Tune polling frequency and retry behavior for foreground/background app states.

## Suggested MVP Cut

Ship v1 with these pieces first:

- Onboarding with server test + bootstrap/pair/token login
- iPhone + iPad adaptive layouts
- Active-session chat with markdown
- Slash-command suggestions and basic command execution
- Session status/details sheet with model switching
- Tool approvals
- Notification permission flow, badges, and local/APNs-ready notification plumbing
- Quick voice dictation
- Dedicated voice screen with simple TTS playback
- Settings + logout

## Post-MVP Ideas

- Server-driven push delivery once the backend exposes device registration
- Home screen widgets / Live Activities
- Better attachment previews
- Saved prompt shortcuts
- Multiple recent sessions browser if mobile usage shows that it is needed

## Definition Of Done For First Public iOS Beta

- A user can connect to a Skitter server from an iPhone without needing desktop-only steps.
- The app resumes the active session reliably and sends/receives messages cleanly.
- Tool approvals are understandable and safe to act on from a phone.
- Voice input feels good enough to use regularly, not like a debug feature.
- Core status, model, and session information are available without cluttering the main UI.
- The app looks intentionally designed, not like a direct port of the menubar client.
