# TASKS — trade-backend

## In Progress
- [2026-03-12] Stabilize agent output parsing for reliable rich fundamental extraction.

## Completed
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
