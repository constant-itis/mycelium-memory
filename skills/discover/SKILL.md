---
name: discover
description: Find hidden connections in the mycelium network — semantic bridges, project hubs, orphan rescue
---

Run `discover()` (the mycelium MCP tool). It looks for connections that
should exist but don't, and creates weak links (0.3-0.5 strength) that will
strengthen through co-access or decay naturally.

Three passes always run:

1. **Semantic bridges** — sample random hot memories, FTS-search for similar
   ones not yet connected, link them.
2. **Project hubs** — connect each project's most-accessed memory to the
   rest of the project's memories.
3. **Orphan rescue** — for memories with zero connections, give each one
   weak link to its closest FTS match.

A fourth pass — **keyword clusters** — only runs if the user has populated
`memory.keyword_clusters` in their config (e.g., vendor names, project
codenames). Skipped silently when empty; that's the default.

Good moments to run:

- Right after seeding a fresh install (helps the new memories find each other)
- Periodically on an active install (idle moments, end of session)
- When `recall()` keeps missing connections you'd expect

After running, show the user the discovery report (how many of each type were
made). The connections are weak by design — they'll either strengthen with
use or fade away on the next decay pass. Cheap to run; safe to repeat.
