# STM — short-term memory hook

A pair of Claude Code hooks that give Claude a small, self-curated buffer of
**operational lessons** — workarounds it discovered when a tool failed in a
recurring way. Lessons are injected as `additionalContext` *before* matching
tools run, so Claude sees the lesson without having to look it up.

This is intentionally separate from mycelium proper. STM is ephemeral, JSON,
6 entries max, lives in `~/.claude/short-term-memory/stm.json`. Promote useful
lessons into mycelium's long-term store with `save()`.

## Install

```bash
bash hooks/stm/install.sh
```

Idempotent. Symlinks hooks into `~/.claude/hooks/`, initializes the empty STM
buffer, patches `~/.claude/settings.json` (with backup), runs a smoke test.

## How it works

- **PreToolUse** → `stm-inject.sh` reads STM, matches tool input against each
  entry's `keywords[]`, and if a keyword appears in the command, returns the
  entry's `lesson` as `additionalContext`. Claude reads it before executing.
- **PostToolUseFailure** → `stm-learn.sh` prompts Claude (via additionalContext)
  to write a lesson if it found a workaround.

Lessons accumulate organically — STM stays empty until Claude actually hits
something worth remembering.

## Schema

`~/.claude/short-term-memory/stm.json`:

```json
{
  "entries": [
    {
      "domain": "short-stable-name",
      "keywords": ["keyword1", "keyword2"],
      "lesson": "What happened, what works, what to avoid.",
      "added": "2026-01-15T12:00:00Z",
      "last_hit": "2026-01-15T12:00:00Z",
      "hits": 0
    }
  ]
}
```

Rules (these belong in your CLAUDE.md so Claude follows them):

- **Max 6 entries.** When full, drop the entry with the lowest `hits`.
- **Same domain replaces old entry** — interference-based displacement, not append.
- **Operational only** — how to do X, what trap to avoid. Not secrets, not config.
- **Promote to mycelium** when a lesson stops being short-term (proven across
  multiple sessions): call `save()` with the lesson content, then delete from STM.

## CLAUDE.md primer (paste into your own CLAUDE.md)

```markdown
## Short-Term Memory (STM)
Live operational buffer at `~/.claude/short-term-memory/stm.json`. Max 6 entries.
Hooks inject relevant lessons as additionalContext before matching tools run.

Self-maintenance:
- When you hit a wall and find a workaround, write the lesson to stm.json.
- Format: `{domain, keywords[], lesson, added, last_hit, hits}`.
- New entry in same domain REPLACES the old one (interference-based displacement).
- If full and a new domain is needed, drop the entry with the lowest hits.
- Lessons are operational (how to do X), not secrets (no IPs, keys, passwords).
- Promote stable lessons to mycelium with save() and remove them from STM.
```

## Files

| File | What |
|---|---|
| `install.sh` | Idempotent installer — symlinks hooks, patches settings.json |
| `stm-inject.sh` | PreToolUse hook — matches keywords, injects lesson |
| `stm-learn.sh` | PostToolUseFailure hook — prompts to capture lesson |
| `stm.json.template` | Empty starting state |

## Uninstall

```bash
rm ~/.claude/hooks/stm-{inject,learn}.sh
# Edit ~/.claude/settings.json to remove the matching hook entries
# (or restore from the .bak.* file the installer left)
```
