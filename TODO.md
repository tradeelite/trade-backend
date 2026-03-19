# TODO — trade-backend

## Features
- [ ] Add structured telemetry for agent extraction path (state-hit vs text-fallback).
- [ ] Add Firebase ID token verification in backend and derive user context from validated token instead of header/cookie passthrough.
- [ ] Add optional X/Twitter data provider integration for Social tab when enterprise API credentials are available.

## Bug Fixes
- [ ] Harden coercion for nested mixed-type numeric fields from agent outputs.
- [ ] Add one-time migration utility to backfill `user_email` on legacy portfolio/option docs.

## Refactoring
- [ ] Move normalization helpers into `app/services/analysis_normalizer.py`.
