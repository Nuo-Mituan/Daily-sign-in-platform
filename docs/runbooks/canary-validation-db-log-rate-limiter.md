# Canary Validation: DB Log Rate Limiter Refactoring (R41-R53)

## Pre-Deployment
- [ ] Confirm `benchmark-regression` job passed on merge commit
- [ ] Verify alert rules are deployed to monitoring stack
- [ ] Baseline current `/api/system/metrics` values for comparison

## During Canary (First 30 Minutes)
### ✅ Healthy Indicators
- `db_log_active_event_types` stabilizes below MAX_EVENT_TYPES (256)
- `db_log_suppressed_total` rate < 50/sec (initial conservative threshold)
- `db_log_overflow_evictions` remains at 0
- Hot path mean latency < 10μs (source: benchmark baseline.json); p99 not available in current benchmark output; use mean as proxy
- No new ERROR logs containing "DB log state desync"

### 🚨 Rollback Triggers
- `db_log_overflow_evictions > 0` sustained for > 1 minute
- `rate(db_log_suppressed_total[5m]) > 200` for > 5 minutes
- Any "DB log state desync" ERROR log appears
- Application error rate increases > 1% vs baseline
- mean latency exceeds 20μs consistently

## Post-Canary (After 24 Hours)
- [ ] Export full metrics snapshot for R53 alert threshold tuning
- [ ] Confirm no silent failures in alerting pipeline
- [ ] Document any deviations from expected behavior in ADR

## Known Limitations
- `/metrics` exposes DB log counters only; pool metrics are available via the authenticated `/api/system/metrics` JSON endpoint.
- Benchmark baseline reports mean/min/max, not p99; use mean as the documented proxy until p99 instrumentation is added.
- Alert thresholds are initial baselines and require tuning after one week of production data.
