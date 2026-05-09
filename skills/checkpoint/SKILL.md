---
name: checkpoint
description: Save session checkpoint to mycelium before /clear or ending work
---

Save a session checkpoint to mycelium, then tell the user it's safe to /clear.

1. Determine: what task/project are you working on, what's done, what's blocked, what's next
2. Call mycelium `save()` with content tagged `[session-checkpoint]` and the appropriate `project` field
3. Keep it dense — one to three sentences max
4. Tell the user: "Checkpoint saved. Safe to /clear."

Format:
```
[session-checkpoint] Working on <X>. Done: <Y>. Blocked: <Z>. Next: <W>.
```
