# Troubleshooting

## Common Discord Problems

### The bot works in DMs but not in a server channel

Check:

- the bot is actually in the server
- the channel is bound in the admin web UI
- the binding uses the correct bot account
- the binding mode matches expected behavior

### A profile does not show up on the shared default bot

That usually means the profile has a dedicated Discord bot override. Shared-default DMs cannot switch to dedicated-bot profiles.

### A public channel seems too chatty

Check whether the binding is:

- `all_messages`
- or `mention_only`

Also remember that busy public sessions now coalesce backlog. One reply may intentionally cover several recent messages.

### A public channel seems too quiet

Check:

- user approval
- binding exists and is enabled
- the bot was mentioned if the mode is `mention_only`

## Common Profile Problems

### A client keeps using the wrong profile

Remember:

- each paired client stores its own active profile
- the user also has a server-side default profile

### A profile exists but has no dedicated bot

That is normal. Profiles can use the shared default Discord bot unless you explicitly create a dedicated override.
