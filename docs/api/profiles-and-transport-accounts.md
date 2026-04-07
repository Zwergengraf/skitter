# Profiles and Transport Accounts API

These APIs power the multi-agent and multi-bot features.

## Profiles

Routes:

- `GET /v1/profiles`
- `POST /v1/profiles`
- `PATCH /v1/profiles/{profile_id}`
- `DELETE /v1/profiles/{profile_id}`

Important behavior:

- users can list their own profiles
- admins can list profiles for a target user
- create supports blank or clone-style creation
- delete only works for archived profiles

## Transport Accounts

Routes:

- `GET /v1/transport-accounts`
- `POST /v1/transport-accounts`
- `PATCH /v1/transport-accounts/{account_key}`
- `DELETE /v1/transport-accounts/{account_key}`

Current transport support:

- dedicated Discord override bots only

The shared default Discord bot is synthetic:

- it is derived from `config.yaml`
- it uses the reserved account key `discord:default`
- it is not deleted through the transport-account API

## Surfaces and Bindings

Routes:

- `GET /v1/transport-accounts/{account_key}/surfaces`
- `GET /v1/transport-accounts/{account_key}/bindings`
- `POST /v1/transport-accounts/bindings`
- `PATCH /v1/transport-accounts/bindings/{binding_id}`
- `DELETE /v1/transport-accounts/bindings/{binding_id}`

Important rules:

- DMs do not require bindings
- public channels do
- the shared default Discord bot requires an explicit target profile when binding
- dedicated bots are pinned to their own profile

## Related Fields

Schedules and jobs can carry:

- `target_origin`
- `target_destination_id`
- `target_transport_account_key`

That keeps delivery on the correct bot identity.
