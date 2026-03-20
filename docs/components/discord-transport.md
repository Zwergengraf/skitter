# Discord Transport

Skitter can connect to Discord through a normal bot account.

Current behavior is intentionally simple:

- DM-only transport behavior: server channels, threads, and group chats are ignored.
- Slash commands are available in DMs with the bot.
- Tool approvals and `ask_user` prompts are supported in Discord.
- Attachments and images from the agent are delivered back into the DM.

## Quick Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a new application.
3. Open the `Bot` page and create or reset the bot token.
4. Enable `Message Content Intent` on the `Bot` page.
5. Open the `Installation` page.
6. Under install scopes, enable:
   - `bot`
   - `applications.commands`
7. For bot permissions, enable at least:
   - `View Channels`
   - `Send Messages`
   - `Read Message History`
   - `Embed Links`
   - `Attach Files`
8. Use the generated install link to add the bot to your own private test server.
9. In `config.yaml`, set your token:

```yaml
discord:
  enabled: true
  token: "YOUR_BOT_TOKEN"
```

10. Restart Skitter:

```bash
./setup.sh restart
```

11. Open a DM with the bot and send a message.

## Notes

- Discord support in Skitter is currently DM-only by design.
- The bot token is sensitive. Do not commit it to git or share it.
- If you do not want Discord at all, disable it in `config.yaml`:

```yaml
discord:
  enabled: false
```

## What This Transport Handles

- Inbound Discord messages are mapped into Skitter message envelopes.
- Slash commands are routed into the same private user session model as other clients.
- Approval requests and `ask_user` prompts are shown with Discord UI components.
- Attachments are ingested and agent-generated files/images are sent back to Discord.
