# Discord Transport

Skitter can connect to Discord through:

- one shared default bot configured in `config.yaml`
- optional dedicated per-profile override bots configured in the admin web UI

## Supported Surfaces

- DMs
- public server text channels
- threads
- slash commands
- button-driven approvals and prompt replies

Public channels are opt-in through bindings. They are not active by default.

## Shared Default vs Dedicated Bots

### Shared default bot

Configured in `config.yaml`:

```yaml
discord:
  enabled: true
  token: "YOUR_BOT_TOKEN"
```

Use this when:

- you want one default bot for most profiles
- you want shared-default DMs
- you want to bind some public channels without creating dedicated bots

### Dedicated profile bot

Configured in the admin web UI:

- stored as a transport account
- token kept in encrypted secrets
- pinned to exactly one profile

Use this when:

- one profile should have its own bot identity
- the shared default bot should no longer act as that profile

## Public Channel Bindings

To activate a normal Discord channel:

1. add the bot to the server
2. open the admin web UI
3. go to `Profiles`
4. select the bot account
5. bind the channel
6. choose a mode

Modes:

- `mention_only`
  - bot wakes on direct mentions, replies to the bot, or explicit interactions
- `all_messages`
  - bot sees every non-self message in the bound channel

## Sender Context

In public channels, Skitter exposes sender metadata to the model:

- display name
- username
- mention token
- role names
- bot flag

This lets the agent reason about who said what while still running under the bound profile owner’s workspace and memory.

## Session Behavior

Public Discord channels use group sessions scoped by:

- origin
- transport account
- external channel

Skitter serializes one active run per session and coalesces backlog by default for plain public-channel messages.

## Mentions

Discord mention tokens work normally if the agent emits the correct token:

- user: `<@USER_ID>`
- role: `<@&ROLE_ID>`
- channel: `<#CHANNEL_ID>`

Skitter also provides the `discord_resolve_mentions` helper tool so agents can resolve mention tokens before replying.

## Approval and Prompt UX

- tool approvals use Discord buttons
- `ask_user` prompts use Discord buttons or free-text replies
- group-channel prompt replies are validated against the correct bound group session

## Security Notes

- the shared default bot token is sensitive
- dedicated bot override tokens are sensitive
- do not commit either kind of token to git
- public channels are approved-users-only
