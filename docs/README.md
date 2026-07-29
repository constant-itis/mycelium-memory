# mycelium docs

Start with **concepts**, then reach for the rest as you need them.

| Doc | What it's for |
|---|---|
| [concepts.md](concepts.md) | Read-once overview — what mycelium actually is and how the pieces (recall, connections, decay, consolidation) fit together. |
| [claude-md-primer.md](claude-md-primer.md) | A snippet to paste into your own `CLAUDE.md` so Claude uses mycelium consistently (recall before asking, save what's worth keeping). |
| [configuration.md](configuration.md) | The single TOML config file, its sections, and the `MYCELIUM_*` env overrides. Zero-config works; override only what you care about. |
| [seeding.md](seeding.md) | Bootstrap a fresh (empty) install — paste-prompts for seeding from an existing `CLAUDE.md`, project trees, notes, or shell history. |
| [local-llm-maintenance.md](local-llm-maintenance.md) | Offload memory upkeep to a local LLM: draft consolidation summaries + an archive/keep proposal, human-verified before deletion. |
| [research/](research/) | Long-form notes on the ideas behind mycelium — memory governance for long-running agent systems. |

New here? [concepts.md](concepts.md) → install (see the [top-level README](../README.md)) → [claude-md-primer.md](claude-md-primer.md).
