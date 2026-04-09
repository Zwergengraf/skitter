# Testing

## Current Important Coverage Areas

- runtime history and prompt reconstruction
- Discord transport behavior
- profile lifecycle
- transport accounts and channel bindings
- session queue serialization and backlog coalescing

## Fast Local Commands

Run everything:

```bash
pytest -q
```

Focused iteration:

```bash
pytest skitter/tests/unit -q
pytest skitter/tests/e2e -q
```

Recent transport/profile targets:

```bash
pytest skitter/tests/unit/test_profile_service.py -q
pytest skitter/tests/unit/test_transport_accounts.py -q
pytest skitter/tests/unit/test_discord_transport.py -q
pytest skitter/tests/unit/test_discord_mentions.py -q
pytest skitter/tests/unit/test_session_run_queue.py -q
pytest skitter/tests/unit/test_runtime_history.py -q
```

## Recommended Next Coverage

- live-ish Discord guild integration tests
- admin-web profile and transport UI smoke coverage
- schedule/job delivery tests across multiple transport accounts
- public-channel prompt reply flows
