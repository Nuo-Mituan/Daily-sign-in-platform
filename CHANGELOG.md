# Changelog

## [1.0.6] - 2026-10-31

### Removed

- **BREAKING (module authors only)**: removed module SVG icon support. `.svg` now returns
  HTTP 415 with detail `SVG 图标已停止支持，请改用 PNG 格式`; Base64 Data URI no longer
  accepts `image/svg+xml`. Decision: a hand-written SVG sanitizer as the sole defense has an
  unacceptable risk/benefit ratio, while rasterizing requires cairosvg/svglib plus system
  dependencies that are not being introduced in this release.

### Changed

- Unified the module icon format set to ico/png/jpg/jpeg/webp across backend suffix↔magic
  checks, frontend extension detection, rules, and documentation.
- Raster icons are always returned as `image/png`; icon responses now include an ETag,
  `Cache-Control: public, max-age=86400, must-revalidate`, and support `304 Not Modified`.
- Icon error responses may include an optional stable `code` field
  (`icon_format_default` / `icon_size_default`); status codes and detail text are unchanged
  (backward-compatible additive field).
- Frontend 413/415 icon messages remain scoped to `/modules/icon`; fallback is code-driven,
  while concrete backend detail (e.g. the SVG deprecation message) is shown when no generic
  code is present.
- `.cursorrules` and `.cursorrules.md` were merged into one authority; the latter is now a
  deprecated stub.
- Icon endpoint 403 detail no longer echoes internal directory names or regex details;
  status code remains 403 and full reason remains in logs.
- Remote icon URLs with an `.svg` pathname (including query strings) are blocked at the
  frontend before any network request.
- Unified frontend icon error handling in one shared function used by both Axios and
  ModuleIcon fetch paths (generic codes fall back to fixed copy; concrete details win).

### Migration

- Replace `config.json` `icon` references ending in `.svg` with PNG (recommended), JPG/JPEG,
  WebP, or ICO. The repository scan found no existing module SVG icons.
- Site favicons (`frontend/public/favicon.svg`) and inline UI `<svg>` brand graphics are not
  module icons and are unaffected.

## Unreleased

### Changed
- Decoupled ADR from test function names via stable Contract IDs with bidirectional validation
- Segregated PBT tests into `tests/property/` with `@pytest.mark.property` for CI performance isolation
- Decoupled `db_logs_suppressed_total` from overflow count; overflow now exposed as independent metric `db_log_overflow_count`
- [BREAKING] Removed the internal `is_new` parameter from `_module_field_values`; create/update both use `_module_field_values(config)` and set `directory_name` explicitly at the create call site. This internal helper has no external callers.

### Added
- Created pbt_bootstrap.py CLI tool for standardized PBT contract scaffolding
- Released State Machine Refactoring Playbook v2.0 with integration hardening patterns from R54-R55
- Published team enablement materials for State Machine Refactoring Playbook
- Team enablement slide deck for State Machine Refactoring Playbook adoption
- Canary validation runbook for DB log rate limiter refactoring with explicit rollback triggers
- Codified alerting rules for DB log rate limiter pressure metrics with metric-name validation test
- CI now automatically blocks merges with >20% hot path performance regression vs main branch
- Exposed DB log rate limiter pressure metrics (active types, suppressed total, overflow evictions) for production observability
- Established micro-benchmarks for rate limiter and pool snapshot hot paths using pytest-benchmark
- Published State Machine Refactoring Playbook documenting R41-R51 methodology
- CI pipeline enforces dual-track testing: fast unit tests + required PBT contract verification
- Exposed suppressed DB log counts in metrics endpoint to prevent silent failure blind spots
- Instrumented connection pool `error` and `invalidate` events to track connection failure rates
- Implemented adaptive decay interval that accelerates cooldown during extreme contention spikes

### Fixed
- Diagnostic endpoint offloads sync pool reads to thread pool to avoid event loop blocking
- Pool metric cache reset is now atomic under concurrent access
- DB log active_event_types now decays correctly when errors stop occurring
- Pool event probes now re-register after Pool recreation instead of silently stalling
- Changed overflow alert from cumulative to rate-based to avoid permanent firing
- Invalidated all metric caches on Pool ID change to prevent stale data leakage
- Added lazy retry for pool event registration on metric read after partial failure
- Corrected Canary Runbook API paths and replaced unavailable p99 with mean latency
- Added /metrics Prometheus text endpoint for alert rule compatibility
- Exposed pool metrics and stripe contention stats via /api/system/metrics diagnostic endpoint
- Added verification status annotations to DESIGN_DECISIONS.md linking each invariant to its PBT test
- Upgraded DB log eviction desync detection from assert to logger.error for production safety under -O flag
- Refactored pool metrics snapshot to iterate over contract keys, ensuring strict output schema and ignoring internal dirty data
- Enforced strict key set equality in DB log rate limiter by explicitly initializing suppressed counts to 0
- Added Property-Based Testing (PBT) using Hypothesis to mathematically verify state machine invariants for rate limiter, pool metrics, and shutdown hooks.
- Added idempotency guard to shutdown decay flush to prevent concurrent file corruption
- Documented pool counter atomicity contract for future free-threaded Python compatibility
- Unified DB log event type eviction into atomic helper to prevent suppressed count desync
- Documented pool metrics snapshot contract and defined metric key constants for export stability
- Wrapped all pool event callbacks in exception handlers to prevent probe failures from disrupting database operations
- Ensured suppressed count consistency with LRU updates in DB log rate limiter to prevent counter drift
- Unified pool metrics namespace with `pool_` prefix in snapshots to prevent key collisions and align with Prometheus conventions
- Replaced `ThreadPoolExecutor` with daemon `threading.Thread` in shutdown flush to prevent `atexit` thread leakage and blocking
- Fixed DB log expiration logic by enforcing LRU order on timestamp updates to prevent stale keys from blocking cleanup
- Wrapped shutdown decay state flush with 2s timeout to prevent blocking on unresponsive filesystems
- Added runtime type validation in pool metrics snapshot to prevent serialization failures
- Decoupled DB log expiration cleanup from capacity check to ensure timely removal of inactive event types
- Added forced decay state flush during graceful shutdown to prevent rate-limiter memory loss on restart
- Isolated pool metrics exposure by returning thread-safe snapshots under lock
- Optimized DB log expiration cleanup with short-circuit iteration to minimize lock hold time
- Removed futile retry of writing fuse marker on read-only directories to clarify persistence failure semantics
- Added Pool ID validation in connection pool event callbacks to ignore stale callbacks from disposed pools
- Ensured atomic FIFO eviction for DB log event types under lock and unified overflow counter to monotonically increasing
- Ensured `PermissionError` during atomic write correctly triggers decay state persistence fuse
- Reset connection pool metrics upon pool recreation to prevent stale data inheritance
- Added max capacity limit and FIFO eviction for DB log event types to prevent memory leaks from dynamic event strings
- Added automatic parent directory creation in atomic JSON writer to handle runtime directory deletion gracefully
- Optimized pool registration lock with double-checked locking to avoid serialization on hot path
- Made `db_logs_suppressed_total` monotonically increasing to support accurate rate() queries; expiration now only affects active type count
- Extracted atomic JSON write helper and applied to decay fuse marker to prevent state file truncation on crash
- Added threading lock around pool event registration to prevent race conditions during concurrent stats access
- Used safe snapshot iteration for DB log cleanup to prevent RuntimeError under concurrent writes and ensure no-GIL compatibility
- Persisted `decay_state_writable` flag in state file to prevent restart loops after persistence failure
- Added retry mechanism for partially failed pool event registrations instead of permanent skip
- Restored atomic cleanup-and-snapshot in DB log stats with lock-free candidate pre-filtering to prevent count loss
- Exposed `decay_state_writable` boolean in contention stats for persistence health monitoring
- Replaced `sa_event.contains()` with application-level registration tracking for robust idempotency
- Split DB log expiration cleanup from stats snapshot to minimize lock contention on hot path
- Implemented auto-fuse mechanism for decay state persistence to stop IO attempts after directory deletion or permission loss
- Added pool object ID tracking to re-register event listeners if the connection pool is recreated
- Added lazy expiration cleanup in DB log stats to ensure active event type metric accuracy
- Added writability pre-check for decay state directory to fail fast with clear error instead of silent IO failures
- Added 5-second sampling cache for instantaneous pool metrics to reduce high-frequency scrape overhead
- Made `db_log_overflow_count` window-based to align with suppression metrics and support direct rate() queries
- Added automatic parent directory creation for decay state file to prevent silent persistence failure
- Replaced cached pool metrics with direct SQLAlchemy Pool API calls for authoritative instantaneous values
- Implemented atomic file replacement for decay state persistence to prevent corruption in multi-worker setups
- Exposed instantaneous pool utilization and checked-out counts for connection leak detection
- Tracked hard-dropped DB logs in overflow counter to eliminate monitoring blind spots
- Added minimum write interval throttling for decay state persistence to reduce IO pressure
- Isolated connection pool event registration to prevent single-event failures from blocking core metrics
- Fixed decay state persistence to use wall-clock time for safe cross-restart monotonic conversion
- Added best-effort file persistence for stripe decay state to survive process restarts
- Improved connection pool event listener compatibility across SQLAlchemy versions with graceful degradation
- Ensured atomic snapshot consistency for DB log suppression metrics
- Replaced hard-cutoff adaptive decay with smooth linear interpolation to prevent metric oscillation
- Prevented duplicate registration of connection pool event listeners during module reloads
- Added memory leak protection to DB log rate limiter by evicting expired event types
- Implemented adaptive stripe decay factor that accelerates cooldown for highly contended locks
- Instrumented connection pool with event listeners to track cumulative connect/checkout/checkin/disconnect rates
- Added time-window rate limiting for DB error logs to prevent log storms during outages
- Exposed decay config version number in contention stats for runtime configuration observability
- Added callback hook for pool metrics cache refresh to support async orchestration workflows
- Reordered log field truncation before credential masking to prevent partial mask tokens and ensure UTF-8 safety
- Unified stripe decay parameter hot-reload into atomic read to prevent transient config inconsistency
- Exposed `invalidate_pool_metrics_cache()` for immediate pool metrics refresh after critical operations
- Added safe truncation to structured DB error log fields to prevent oversized log records
- Stripe decay parameters now support runtime hot-reload via environment variables without restart
- Added 5-second TTL cache for connection pool metrics to reduce sync overhead in event loop
- Ensured all structured log extra fields are JSON-serializable primitives to prevent log loss
- Stripe decay threshold and interval are now configurable via STRIPE_DECAY_* environment variables
- Stripe contention stats endpoint now exposes connection pool health metrics (size, checked-in/out, overflow)
- DB error logs now emit structured extra fields for reliable log aggregation and alerting
- Added zero-clamp threshold to stripe contention decay to eliminate floating-point residue accumulation
- Added conditional DEBUG-level logging for full DB error tracebacks while keeping ERROR logs sanitized
- Hardened DB credential sanitization regex with URL boundary anchors to prevent cross-field false positives
- Smoothed stripe lock contention decay using exponential float reduction to eliminate monitoring jaggedness
- Sanitized database credentials from global OperationalError logs to prevent password leakage
- Enabled `pool_pre_ping` on database engine to transparently recover from stale connections
- Stripe decay timestamp access is now fully thread-safe via _STRIPE_GUARD
- Upload session-rebuild integration test now verifies fresh session identity and connectivity
- TestClient test for 500 error now uses isolated FastAPI instance to prevent global route pollution
- Documented concurrency assumptions for stripe decay timestamp read
- Completed upload session-rebuild integration test with minimal auth context mock
- Added end-to-end TestClient test verifying non-connection OperationalError returns proper 500 JSON response
- Added integration tests for session-rebuild paths to verify real DB interactions
- Stripe contention stats returns zeros when data is stale to prevent misleading monitoring alerts
- Global 503 handler now explicitly raises HTTPException(500) for non-connection errors instead of relying on None fallthrough
- Added direct unit tests for session-rebuild helper functions
- Stripe contention stats getter is now a pure function without side effects
- Global 503 handler now inspects underlying cause to distinguish connection failures from transient DB errors
- Global exception handler now catches SQLAlchemy connection errors and returns 503 instead of 500
- Stripe lock contention metrics now use time-based decay to reflect current system load
- Replaced `type: ignore` in route session rebuild with early-return pattern to restore static type safety
- 503 response for database unavailability now conforms to OpenAPI schema
- Routes now explicitly close the original DB session after module sync retry to prevent use-after-corruption
- Double session failure during sync raises 503 instead of leaking internal errors
- Per-key sync locks now use striped hashing to prevent unbounded memory growth
- Module sync retry adds defensive explicit commit on fresh session to guard against future internal refactoring
- Module sync lock granularity reduced from global to per-key; different modules now process concurrently within the same worker
- `_create_or_get_module` now uses SAVEPOINT for conflict isolation; outer transaction is never rolled back on retry failure
- Icon decode pool now tracks submitted decode events instead of reading CPython private `_threads` attributes.
- Icon pool environment variables are validated lazily on first icon request, so importing the module never raises on invalid environment values.
- Tracked icon decode events are set during shutdown, including forced timeout paths.

### Verification

```bash
# Backend only; frontend is intentionally excluded from this search.
grep -RIn "is_new\|_module_field_values" backend/app
```

### Configuration

- `ICON_DECODE_POOL_SIZE` (default 4)
- `ICON_DECODE_POOL_MAX` (default 16)
- `ICON_DECODE_TIMEOUT` (default 10.0 seconds)
- `CONCURRENT_RETRY_DELAY` (default 0.05 seconds) — delay before retrying after concurrent create conflict

### Notes
- R41-R51 refactoring cycle officially closed; core state machine modules are now contract-guarded
- All future changes to rate limiter, pool metrics, or shutdown hooks must follow playbook phases
- Published State Machine Refactoring Playbook at `docs/playbooks/state-machine-refactoring.md`

### Notes
- R52 shifts focus from logical correctness (R41-R51) to performance baselines and production monitoring

### Notes
- R53 completes the observability loop: metrics exposed (R52) → alerts defined (R53) → CI enforces performance (R53)
- Alert thresholds (100/sec suppression, any overflow) are initial baselines; tune after 1 week of production data

### Notes
- R54 prepares R41-R53 work for production deployment and organizational knowledge transfer
- Next step: Execute canary validation during next maintenance window

### Notes
- R56 transitions R41-R55 learnings into reusable organizational assets
- Teams adopting PBT should use pbt_bootstrap.py + Playbook v2 as starting point

### Notes
- R57 addresses state machine boundary conditions and async safety gaps found in R55 post-fix audit
- Playbook v2.1 updated with "State Transition Boundary Testing" pattern
