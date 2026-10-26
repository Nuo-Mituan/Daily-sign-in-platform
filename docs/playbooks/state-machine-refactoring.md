# State Machine Refactoring Playbook v2.1

> **v2.0 (R55)**: Added Integration Validation Checklist, lazy retry pattern, cache invalidation protocol, and alert semantic guidelines based on R54 audit findings.
> **v1.0 (R53)**: Initial release covering R41-R53 methodology.

## Quick Start
```bash
python tools/pbt_bootstrap.py rate_limiter   --invariants "token_bucket_never_negative,burst_respects_max"
```
Then follow Phase 1 of this playbook.


## When to Use
- Module has implicit state transitions not captured in types
- Bug fixes repeatedly introduce regressions in adjacent logic
- Invariants are documented only in developer's head

## Phase 1: Capture Invariants (R41-R43)
- Extract state machine into pure functions where possible
- Document invariants in DESIGN_DECISIONS.md BEFORE fixing bugs
- Write failing tests that express invariants, not just examples

## Phase 2: Property-Based Verification (R44-R47)
- Introduce Hypothesis; start with max_examples=50 for fast iteration
- Mark invariant violations as xfail to avoid blocking CI during exploration
- Never modify business code until PBT reliably reproduces the violation

## Phase 3: Contract Alignment (R48-R49)
- Fix implementation to satisfy xfail tests, then remove xfail marker
- Upgrade dev-only asserts to production-safe logger.error + best-effort recovery
- Add Verification Status section to ADR linking each invariant to PBT

## Phase 4: Infrastructure Lock-in (R50-R51)
- Segregate PBT into separate directory with custom pytest marker
- Decouple ADR from test names via stable Contract IDs
- Add bidirectional validation test between ADR and PBT docstrings
- Bind PBT as required CI check; document enforcement in ADR

## Anti-Patterns to Avoid
- ❌ Fixing bugs without first writing an invariant test
- ❌ Using assert for state validation in production code paths
- ❌ Referencing test function names directly in documentation
- ❌ Running PBT in default test suite (blocks fast feedback loop)

## Phase 5: Performance & Observability Baseline
- Add micro-benchmarks for contract-guarded hot paths
- Expose internal pressure metrics (suppressed, overflow, active types)
- Set CI regression thresholds and alert on rate changes

## Phase 6: CI Regression Guard & Alerting as Code
- Add benchmark regression checks with an explicit degradation threshold
- Define alert rules as version-controlled code and validate metric names in CI
- Keep alert thresholds configurable; start conservative and tune with production data

### Integration Validation Checklist (Post-Implementation)
- [ ] All metrics referenced in alerts are exposed via /metrics endpoint
- [ ] Diagnostic API returns all documented fields with non-null values
- [ ] Runbook paths and thresholds match actual API responses
- [ ] Lazy initialization/retry exists for components that may fail at startup
- [ ] Cache invalidation covers all state reset paths
- [ ] Alert expressions use correct metric names and semantics (rate vs cumulative)

## Phase 7: Production Hardening & Audit Response
- Conduct integration audit using "Integration Validation Checklist" before declaring module complete
- Implement lazy initialization with throttling for components that may fail at startup
- Ensure all state reset paths invalidate associated caches atomically
- Validate alert expressions against actual metric names and semantics (rate vs cumulative)
- Document known limitations in Runbooks to prevent SRE confusion during incidents

### State Transition Boundary Testing
- Always test state flags (e.g., FULLY_REGISTERED) against underlying resource identity changes
- Verify cleanup/decay logic runs on read paths, not just write paths
- Validate cache invalidation is atomic with state reset under concurrency
- Ensure async endpoints never execute sync I/O without to_thread()

## Appendix: Common Integration Pitfalls

| # | Pitfall (R54 audit) | Fix pattern |
|---|---|---|
| 1 | Metrics computed but never exposed by an API | Add fields to the diagnostic endpoint and contract-test them |
| 2 | Alerts reference metric names the exporter never emits | Validate alert names against exporter constants in CI |
| 3 | Runbook references wrong endpoint or unavailable p99 | Use actual API path; document metric limitations |
| 4 | Startup-only registration never retried after failure | Add throttled lazy retry on metric reads |
| 5 | Pool/state reset leaves stale metric caches | Invalidate all related caches on reset |
| 6 | Cumulative counter used as a permanent alert | Use rate()/increase() for recent-window alerts |

---
Last Reviewed: 2026-10-25
Owner: Architecture Team
