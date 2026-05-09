---
name: maintain
description: Run mycelium maintenance — snapshot, identify duplicates/superseded, rescue orphans
---

Run a maintenance pass on the mycelium memory network. Default behavior is
**always show the plan first, then ask before applying.**

1. Call `maintain()` (the mycelium MCP tool) with default args. This is dry-run
   — it returns the snapshot baseline and the plan, but writes nothing.
2. Show the user the plan: how many session-checkpoint duplicates would be
   demoted, how many superseded memories would be cold-marked, how many orphan
   rescues would create new connections.
3. **Ask the user to approve before executing.** If they say yes, call
   `maintain(execute=True)`. Default backup is on; mention where the snapshot
   will be written.
4. After execution, show the post-execution summary (cold-marked count, new
   edges count, orphans remaining).

If the user wants different guards, you can pass `recent_days=N` (protect
anything accessed in the last N days, default 7) and `confidence_floor=X`
(protect anything with confidence >= X, default 0.8).

Don't run `execute=True` without user confirmation.
