# State Machine Refactoring: From Whack-a-Mole to Contract-Guarded Design

## The Pain (Before R41)
- 3 production incidents in 2 months from "fix one bug, create two more"
- Invariants lived only in senior engineer's head
- Tests verified examples, not properties

## The Turning Point (R44: First PBT)
- Hypothesis found a desync bug in 8 seconds that manual testing missed for weeks
- Key insight: "If you can't express it as a property, you don't understand it"

## The Transformation (R41-R53 Journey)
- Show before/after code diff for `_evict_event_type`
- Demo: Live PBT finding a regression in real-time
- Metrics: 0 regressions in 6 months post-PBT adoption

## Your Turn: Applying the Playbook
- Identify candidate module using "When to Use" checklist
- Schedule 2-hour pairing session with architecture team
- First PBT should take < 1 day; if longer, invariant is too broad

## Q&A Prompts
- "What if my state machine has side effects?"
- "How do I convince my team to invest time in PBT?"
- "When is PBT overkill?"
