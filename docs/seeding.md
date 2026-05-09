# Seeding mycelium from your existing stuff

A fresh mycelium install starts empty. You can wait for memories to accumulate
naturally — that's the intended steady state — or you can seed it once from
material you already have lying around so `recall()` is useful from day one.

The pattern below is the same one used elsewhere in this repo: hand Claude a
constrained prompt, let it read your files and call `save()` many times. No
new tooling required.

**Before any seeding session:** open Claude Code and confirm mycelium is
connected (`claude mcp list` should show it). Then paste a recipe.

---

## Recipe 1: from your existing CLAUDE.md / AGENTS.md / project notes

You probably already wrote down a lot of facts there. Convert them into
discrete memories so they're searchable across projects.

````
Read my CLAUDE.md (and any AGENTS.md or notes/*.md files I have in this
project) and seed mycelium memories from the durable facts you find.

Rules:
- One idea per save() call. Keep each memory short and dense.
- Use project="<this-project-name>" on every save.
- Save: project structure, key file paths, service ports, runbooks, conventions
  I've documented, gotchas, decisions and their rationale.
- DO NOT save: secrets/keys/passwords, anything obviously stale, anything fully
  derivable from `git log` or just reading the file.
- If save() reports a duplicate, accept the suggestion to skip — don't force.
- Pin (pin(memory_id)) anything that's a confirmed fact I've manually verified.

Report a summary at the end: how many memories saved, how many skipped as
duplicates, anything you noticed was risky to save.
````

---

## Recipe 2: from a project tree scan

If you have a `~/projects/` (or similar) with several active codebases, a
one-memory-per-project summary makes `context()` immediately useful.

````
Scan my project directories at ~/projects (max depth 2). For each project
directory you find:

1. Look at the README, package.json/pyproject.toml/Cargo.toml, and top-level
   structure to understand what it is.
2. Save one memory per project to mycelium with project="<dir-name>".
3. Memory content should be: 1-2 sentences on what it is, key tech stack,
   notable services/ports if any, status if obvious (active / archived).
4. Skip directories that are obviously not projects (.git, node_modules, etc.).

Don't open Claude Code on each one — just summarize from the surface. If
something is unclear, save what you know and flag the unclear bit.

Report what got seeded and anything that needs a follow-up dive.
````

---

## Recipe 3: from a curated seed file you write yourself

If you want full control, write a plain-text file with one memory per
bullet, then have Claude turn each bullet into a `save()` call.

```markdown
<!-- seed.md -->
# project: acme-api

- The API runs at https://api.acme.example/v2 — version pinned, breaking changes go to /v3.
- Database is Postgres 16 on the staging cluster; production uses RDS.
- We use pino for structured logs; logs flow into Loki via Promtail.

# project: acme-web

- Next.js 15 with App Router; deployed to Vercel.
- Auth is NextAuth with the company SSO provider.
```

Then:

````
Read seed.md. For each bullet under each `# project: NAME` heading, call
mycelium save() with that bullet as the content and project="NAME". Keep
the wording almost verbatim — these are facts I've already curated.
````

---

## Recipe 4: distill the current conversation

Best way to capture lessons in real time. Run this at the end of a session
where you taught Claude something useful.

````
Look back over this conversation and identify the durable lessons —
the things that took us time to figure out and that next session would
benefit from already knowing. For each one, save() it to mycelium with
an appropriate project tag.

Skip ephemeral session state ("we were editing line 42"). Save the
why ("we use approach X because approach Y broke Z way") and the
how ("the workaround for the WAL contention is busy_timeout=5000").

Then call /checkpoint to save the session checkpoint.
````

---

## Recipe 5: from shell history

For ops/dev environments where the same useful commands recur.

````
Read my recent shell history (`tail -500 ~/.bash_history` or
`tail -500 ~/.zsh_history`). Identify command patterns I clearly use
repeatedly — deploy commands, build pipelines, db migrations, log queries,
SSH targets, etc.

For each recurring pattern, save() one memory describing what the command
does and when I'd run it. Use a project tag like "ops" or the relevant
service name if obvious.

Skip: one-off commands, anything with secrets/tokens in the args, anything
trivial (`ls`, `cd`, `git status`).
````

---

## After seeding

```bash
mycelium config             # confirm DB path
sqlite3 ~/.mycelium/memory.db "SELECT COUNT(*) FROM memories"   # gut-check the count
```

Then in Claude Code:

```
context()                   # see what surfaced as hub memories
recall("something you seeded")
discover()                  # let mycelium find connections among the new memories
```

If you over-seeded and want to undo, the simplest reset is:

```bash
rm ~/.mycelium/memory.db ~/.mycelium/memory.db-wal ~/.mycelium/memory.db-shm
```

Next call to mycelium re-creates an empty DB.

## Don't over-seed

A fresh install with 50 thoughtfully-curated memories outperforms one with
500 noisy ones. The network gets its power from co-access patterns over time;
seed enough to bootstrap, not enough to drown the signal.
