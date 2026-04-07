# Authentication and Device Pairing

This page explains how you log in to Skitter and how to add more clients to the same human account.

## Mental Model

- `Admin API key` is for server administration and the admin web UI.
- `User access token` is for normal day-to-day clients.
- Each human `User` can own multiple `AgentProfile`s.
- Pairing links a new client to the same human account, not to one fixed profile.
- Each client can then choose its own active profile.

## First Login

Use `SKITTER_BOOTSTRAP_CODE` to create the first user token.

Typical flow in TUI or menubar:

1. Enter API URL.
2. Enter setup code.
3. Enter your display name.
4. Client receives and stores a user token.

Notes:

- The first local user is automatically approved.
- You only need the setup code for first-time bootstrap on a new install.

## Pairing More Devices

After one client is logged in:

1. On an existing client, run `/pair`.
2. On the new client, choose `Pair` and enter the code.
3. The new client receives its own user token and is linked to the same user account.

Pair codes are one-time and short-lived.

## Profiles After Pairing

Pairing does not force all clients onto one profile.

- Menubar can use profile `default`
- TUI can use profile `coder`
- Discord DM on the shared default bot can use another selectable profile
- a dedicated Discord bot can be pinned to exactly one profile

## Discord and Approval

Discord is approval-gated for all users.

- When a Discord user messages the bot for the first time, a user record is created.
- That user must be approved in the admin web UI before they can use the agent.
- In DMs, unapproved users get a not-approved notice.
- In public server channels, unapproved users are ignored.

## Discord Profile Selection

There are three main Discord modes:

- shared default bot in DM:
  - `/profile use` can switch between profiles that do not have dedicated Discord bots
- dedicated per-profile bot:
  - pinned to one profile
  - `/profile use` is rejected
- public server channel binding:
  - profile is chosen by admin binding
  - `/profile use` is rejected in that channel

## Admin Key vs User Token

- Admin web UI and admin-only APIs: admin API key
- TUI, menubar, and custom user clients: user token

Do not manually copy one user token between devices. Pair each device instead.
