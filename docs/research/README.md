# docs/research/

Long-form notes about how this thing is supposed to work in the broader
sense — the architectural ideas behind mycelium that go beyond "two SQLite
files and an MCP server."

These docs are **research direction**, not feature documentation. The OSS
package in this repo implements a subset of what's described here; the rest
is what mycelium *could* be in a fuller agent-runtime context.

If you want to know what the shipped code does, read the main
[README](../../README.md) and [docs/concepts.md](../concepts.md). If you want
the broader theory of memory governance for long-running agents, read on.

## Contents

| File | What |
|---|---|
| [mycelium-memory-governance.md](mycelium-memory-governance.md) | Long-form notes on memory governance — the event → trace → pattern → lesson → procedure → tool transition chain, the context-economy framing, why semantic and behavioral memory belong in separate stores, and what verifier-driven learning looks like. |
