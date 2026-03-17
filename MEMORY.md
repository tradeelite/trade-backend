# MEMORY — trade-backend

## Current State

- Stable full endpoint: `GET /api/stocks/{ticker}/ai-analysis`
- New dedicated endpoint: `GET /api/stocks/{ticker}/fundamental-analysis`
- Both endpoints use in-memory cache (10 minutes per ticker).
- Portfolio and options routes are now user-scoped by `user_email`.

## Normalization Strategy

- `_normalize_analysis()` standardizes orchestrator payloads for frontend.
- `_normalize_fundamental_only()` normalizes dedicated fundamental payloads.
- `_ensure_enhanced_fundamental_shape()` backfills `attributes`, `aiAnalysis`, `sources` when upstream returns legacy-only fields.

## Runtime Notes

- Production URL: `https://trade-backend-s33r4afwbq-uc.a.run.app`
- Active stable agent resource:
  - `projects/685436576212/locations/us-central1/reasoningEngines/8106143978220421120`
- User context ingestion for owned data routes:
  - Primary: `x-user-email` request header
  - Fallback: `userEmail` query param
  - Last fallback: `ALLOWED_EMAIL` for single-admin compatibility
- Admin resolution:
  - Primary: `ALLOWED_EMAIL` env
  - Fallback: earliest `allowed_users` record (for env-missing deployments)
- Legacy ownership recovery (2026-03-17):
  - Backfilled `user_email=admin@tradeelite.ai` to 3 ownerless `portfolios` docs

## Known Gaps

- ADK session-state extraction can still be intermittent in some agent revisions.
- Additional tests needed around mixed-type numeric coercion and backfill logic.
- Header-based user context is not cryptographically verified yet (token verification pending).
