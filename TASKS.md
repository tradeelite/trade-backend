# TASKS — trade-backend

## In Progress
- [2026-03-12] Stabilize agent output parsing for reliable rich fundamental extraction.

## Completed
- [2026-03-17] Admin/regular settings access control + legacy ownership recovery
  - Added admin resolution fallback (uses `ALLOWED_EMAIL`; if missing, earliest allowlisted user)
  - Added `require_admin_user` dependency and enforced admin-only writes for:
    - `/api/settings` (PUT)
    - `/api/users` (list/add/remove)
  - Extended `/api/users/check` with `is_admin` and `admin_email`
  - Added `/api/users/me` endpoint for frontend role-aware settings UX
  - Updated `cloudbuild.yaml` to include `ALLOWED_EMAIL` in backend runtime env
  - Ran one-time Firestore backfill for legacy ownership: assigned `user_email=admin@tradeelite.ai` to 3 ownerless portfolios
- [2026-03-17] Added multi-user data isolation for portfolios and options.
  - Added request user dependency (`x-user-email` / `userEmail`) for user-owned routes
  - Repositories now store/filter by `user_email`
  - Added ownership checks for portfolio/holding/trade read-write-delete paths
  - Kept backward compatibility for legacy docs (missing owner) for admin only
- [2026-03-12] Added `/api/stocks/{ticker}/fundamental-analysis` endpoint.
- [2026-03-12] Added enhanced fundamental schema backfill when upstream model returns legacy shape.
- [2026-03-12] Deployed new backend revisions with stable agent resource rollback strategy.

---
_Format: `- [date] description — notes`_
