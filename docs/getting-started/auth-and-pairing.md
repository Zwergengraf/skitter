# Auth and Pairing

Skitter has two authentication modes for `/v1/*` routes.

## Auth Modes

### 1) Admin API key

Use for admin operations and automation:

- Header `x-api-key: <SKITTER_API_KEY>`
- or `Authorization: Bearer <SKITTER_API_KEY>`

### 2) User access token

Use for normal client access (TUI/menubar/custom client):

- Header `Authorization: Bearer <user_token>`

User tokens are issued by bootstrap/pairing endpoints.

## Public Auth Endpoints

These routes are intentionally accessible without existing auth:

- `POST /v1/auth/bootstrap`
- `POST /v1/auth/pair/complete`

All other `/v1/*` routes require valid admin key or user token.

## First Device / First Account: Bootstrap Flow

Use bootstrap when you do not have a token yet.

1. Set `SKITTER_BOOTSTRAP_CODE` on server.
2. Call:

```http
POST /v1/auth/bootstrap
```

with:

```json
{
  "bootstrap_code": "YOUR_CODE",
  "display_name": "Your Name",
  "device_name": "macbook",
  "device_type": "menubar"
}
```

3. Server returns:
  - `token`
  - user info (`id`, `display_name`, `approved`)

The created local primary user is auto-approved.

## Pairing Additional Devices

Use pairing when a user already exists and has a valid token.

1. Create pair code:
  - `POST /v1/auth/pair-codes` with user token
  - or Discord `/pair` command in DM
2. Complete on new device:

```http
POST /v1/auth/pair/complete
```

with:

```json
{
  "pair_code": "ABCD-EFGH",
  "device_name": "laptop",
  "device_type": "tui"
}
```

3. Receive new user access token for that device.

Defaults:

- Pair code default TTL is 10 minutes.

## Approval Gating

- Newly created Discord users are not approved by default.
- Unapproved users get blocked until approved in Admin UI.
- Pending unapproved users are auto-pruned after 15 minutes if they remain unapproved.

## Common Failure Cases

- `401 Missing authentication credential`: no header on protected route.
- `401 Invalid authentication token`: bad/revoked/expired token.
- `401 Invalid bootstrap code`: wrong `bootstrap_code`.
- `400 Invalid or expired pair code`: code typo/expired/used.
- `403 Your account is not yet approved`: user exists but not approved.
- `400 user_id is required for admin requests` on `/v1/auth/me`:
  - admin auth requires `?user_id=<internal_user_id>`
  - user token does not require `user_id`.
