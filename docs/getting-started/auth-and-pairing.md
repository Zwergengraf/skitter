# Authentication and Device Pairing

This page explains how you log in to Skitter and how to add more clients (TUI, menubar app, Discord DM) to the same account.

## Quick Mental Model

- `Admin API key` is for server administration and the admin web UI.
- `User access token` is for normal day-to-day chat clients.
- Each client device gets its own token.
- New devices are added with a short-lived `pair code`.

## First Login (First Device)

Use the server `setup code` (configured as `SKITTER_BOOTSTRAP_CODE`) to create your first local user token.

Typical flow in TUI or menubar:

1. Enter API URL.
2. Enter setup code.
3. Enter your display name.
4. Client receives and stores a user token.

Notes:

- This first local user is automatically approved.
- You only need the setup code for first-time bootstrap on a new installation.

## Pairing Additional Devices

After one client is already logged in, pair new devices without using the setup code again.

1. On an already logged-in client, generate a pair code:
  - TUI/menubar/Discord DM: run `/pair`
2. On the new client, choose `Pair` and enter that code.
3. The new client receives its own user token and is linked to the same user account.

Pair code behavior:

- One-time use.
- Short-lived (default: 10 minutes).

## Discord and Approval

Current Discord mode is DM-only.

- If a Discord user DMs the bot for the first time, a user record is created.
- That user must be approved in the admin UI before they can use the agent.
- While unapproved, Discord replies are blocked (after the initial not-approved notice).

## Admin Key vs User Token

Use the right credential for the right job:

- Admin web UI and admin API actions: admin API key.
- TUI, menubar, custom user clients: user token.

Do not share user tokens between devices manually. Pair each device instead.

## Common Problems

- `Connection failed` during first login:
  - Check API URL and setup code.
- `Invalid or expired pair code`:
  - Generate a new code and pair again.
- `Your account is not yet approved`:
  - Approve the user in admin UI.
- Client works but a new device cannot pair:
  - Ensure you created the pair code from a logged-in, approved account.
