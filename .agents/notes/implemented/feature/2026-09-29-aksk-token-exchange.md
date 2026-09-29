# Decision: Implement AK/SK → API Key token exchange (experimental)

Status: implemented
Implemented: 2026-09-29

## Problem
Users with Alibaba Cloud AK/SK credentials cannot directly authenticate with
the FC Agent Sandbox API, which requires an API Key. Manually obtaining an API
Key adds friction to the onboarding flow, especially for enterprise users who
already have AK/SK credentials provisioned through their cloud account.

## Decision
Implement an **experimental** token exchange mechanism that converts AK/SK
credentials into a temporary API Key:

- Use Alibaba Cloud RPC POP V1 HMAC-SHA1 signature to call the `fcsandbox`
  endpoint with action `CreateApiKey`.
- The response returns a temporary API Key with TTL of 3600 seconds.
- Auto-refresh is triggered 5 minutes before expiry (assumed value, pending
  platform confirmation).
- **Note:** The endpoint action name (`CreateApiKey`) and response field names
  are pending FC platform confirmation and may change.

### Error handling
- New error type `TokenExchangeError` (E1004) under the Authentication error
  category for exchange failures (invalid credentials, endpoint unavailable,
  etc.).

## API Design

```python
async def exchange_aksk_for_api_key(
    access_key_id: str,
    access_key_secret: str,
    *,
    region: str = "cn-hangzhou",
) -> str:
    """Exchange AK/SK for a temporary API Key via FC platform."""
    ...
```

## Alternatives considered
- **Require users to manually create API Keys** — poor UX for enterprise users
  with existing AK/SK credentials. Rejected.
- **Use STS token directly** — the sandbox API does not accept STS tokens
  natively; an API Key is required. Rejected.

## Dependencies
- `hmac`, `hashlib` (stdlib) for HMAC-SHA1 signing
- Existing `transport.http` module for HTTP requests

## Test Strategy
- Unit tests mock the FC endpoint response to verify signature construction
  and token parsing.
- Error path tests verify `TokenExchangeError` (E1004) is raised on invalid
  credentials and network failures.

## Acceptance criteria
- ⚠️ `exchange_aksk_for_api_key()` returns a valid temporary API Key — **Pending platform confirmation**
- ⚠️ Invalid AK/SK raises `TokenExchangeError` (E1004) with actionable message — **Pending platform confirmation**
- ⚠️ Token refresh is triggered before expiry — **Pending platform confirmation**
- ✅ Marked as experimental in docstrings and public API docs

> **Verification caveat:** the ⚠️ items above are covered only by unit tests that
> mock the FC endpoint response — they have **not** been exercised against the
> real FC endpoint. The endpoint action name (`CreateApiKey`) and the response
> field names are still **pending confirmation from the FC platform team**.
