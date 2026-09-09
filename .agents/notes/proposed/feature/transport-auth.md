# Decision: Authentication Module

Status: proposed

## Problem
Dual auth (API Key + AK/SK) with dual token (Platform X-API-KEY + envd X-Access-Token). Need a clean abstraction for header injection and token lifecycle.

## Decision
- `ApiKeyAuth`: reads `SANDBOX_API_KEY` from env/config, injects `X-API-KEY` header
- `AkSkAuth`: exchanges `ALICLOUD_ACCESS_KEY_ID` + `ALICLOUD_ACCESS_KEY_SECRET` for temporary API key (TTL=3600s, auto-refresh at TTL-300s)
- `envdAccessToken` cached per sandbox instance, injected as `X-Access-Token` header for envd API calls

Auth provider is selected automatically based on available credentials, with API Key taking priority.

## Alternatives considered
- **Single auth class** — Mixes concerns, harder to test
- **Middleware pattern** — Over-abstraction for two simple auth modes

## Dependencies
- `transport/http.py` for making auth exchange requests
- `models/config.py` for credential storage

## Test Strategy
- Header injection verification for both auth modes
- Token refresh timing (refresh at TTL - 300s)
- Token cache hit/miss behavior
- Graceful handling of invalid credentials

## Acceptance criteria
- Authenticated requests to both Platform and envd APIs succeed
- Token auto-refresh works before expiry
- Clear error messages for missing/invalid credentials
