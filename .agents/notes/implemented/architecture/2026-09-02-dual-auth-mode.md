# Decision: Dual Authentication Mode (API Key + AK/SK)

Status: implemented

## Problem
Users need to authenticate with the sandbox service. E2B uses a single API Key, but Alibaba Cloud ecosystem users typically use AccessKey ID/Secret (AK/SK).

## Decision
Support both authentication modes:
1. **API Key** (primary): `SANDBOX_API_KEY` env var → `X-API-KEY` header for Platform API
2. **AK/SK** (extension): `ALICLOUD_ACCESS_KEY_ID` + `ALICLOUD_ACCESS_KEY_SECRET` → exchange for temporary API Key (TTL=3600s, auto-refresh 5min before expiry)

After sandbox creation, envd API uses `envdAccessToken` returned in create response, sent as `X-Access-Token` header.

## Alternatives considered
- **API Key only** — Excludes Alibaba Cloud AK/SK users
- **AK/SK only** — Breaks E2B compatibility
- **OAuth2** — Over-engineered for SDK use case

## Dependencies
- `models/config.py` for credential configuration
- `transport/auth.py` for token management

## Test Strategy
- Unit test each auth mode independently
- Test token refresh timing (expiry - 5min)
- Test fallback when primary auth fails

## Consequences
- Seamless migration for both E2B users and Alibaba Cloud users
- Token cache in memory only (no disk persistence for security)
