# Configuration

Mycelium reads from one TOML file. Built-in defaults exist so zero-config works;
override only what you care about.

**Resolution order:** CLI args > env vars > config file > defaults.

**Config file search paths** (first match wins):

1. `--config <path>` flag
2. `$MYCELIUM_CONFIG`
3. `$XDG_CONFIG_HOME/mycelium/config.toml`
4. `~/.config/mycelium/config.toml`
5. `~/.mycelium/config.toml`

**Env vars:** `MYCELIUM_<SECTION>_<KEY>` — e.g. `MYCELIUM_SERVER_PORT=9000`,
`MYCELIUM_STORAGE_DB_PATH=/data/memory.db`. Nested keys use double underscore:
`MYCELIUM_FOUNDRY__RETENTION__MAX_ROWS=1000000`.

`mycelium config` prints the effective config and where it was loaded from —
your single source of truth when something feels off.

---

## `[server]`

| Key | Default | What it does |
|---|---|---|
| `host` | `127.0.0.1` | Bind address. Set to `0.0.0.0` for HTTP transport on a LAN. |
| `port` | `8200` | HTTP port. Ignored in stdio mode. |
| `transport` | `"stdio"` | `"stdio"` for one-client-per-process (the default for Claude CLI). `"http"` for multi-client / multi-machine. |
| `log_level` | `"info"` | `"debug"` is loud but useful when tools aren't behaving. |

**When you'd change these:** `transport = "http"` + `host = "0.0.0.0"` if you
want multiple machines (or both Claude + Codex on different boxes) hitting the
same memory store.

## `[storage]`

| Key | Default | What it does |
|---|---|---|
| `db_path` | `~/.mycelium/memory.db` | Where the semantic SQLite lives. |
| `backup_dir` | `~/.mycelium/backups` | Where maintenance tools write snapshots. |

**When you'd change these:** put the DB on faster storage (NVMe), or pin it to
a directory you already back up.

## `[memory]`

The core knobs that shape the neural-network behavior.

| Key | Default | What it does | When to change |
|---|---|---|---|
| `decay_tau_days` | `30.0` | Connections decay as `strength * exp(-days / tau)`. Lower = faster forgetting. | Drop to 14 if your memory bloats with stale stuff; raise to 60 if recall keeps missing facts you remember from a few months ago. |
| `prune_threshold` | `0.05` | Connections weaker than this get deleted on the next decay pass. | Raise toward `0.1` to keep the network leaner; lower toward `0.01` to retain more weak signals. |
| `auto_connect_limit` | `5` | How many similar memories `save()` auto-links to. | Raise for denser networks, lower if you're seeing too much noise in `recall()`. |
| `hub_limit` | `15` | How many hub memories `context()` returns. | Raise if your context() output feels too thin; lower for terse session starts. |
| `recall_propagate` | `8` | How many neighbors `recall()` walks to from each direct hit. | Raise for "find related stuff" use; lower for sharp lookups. |
| `consolidation_threshold` | `10` | Per-project hot-memory count that triggers a "consider consolidating" nudge in `save()` output. | Raise if you tolerate larger projects without merging. |
| `pinned_decay_floor` | `0.5` | Pinned memories' connections never decay below this strength. | Raise toward `1.0` to make pinned memories effectively permanent. |
| `keyword_clusters` | `[]` | Keywords that `discover()` uses to bridge memories sharing any of them. | Set to a list of your domain terms (vendor names, project codenames) so `discover()` builds those structural bridges. Leave empty to skip the pass. |

Example:

```toml
[memory]
decay_tau_days = 45
keyword_clusters = ["acme corp", "northwind", "contoso"]
```

## `[foundry]`

The behavioral memory card — append-only decision log.

| Key | Default | What it does | When to change |
|---|---|---|---|
| `enabled` | `true` | When `false`, `log_decision`/`query_decisions` tools aren't registered at all. | Turn off if you're only using semantic memory and want a leaner tool surface. |
| `log_dir` | `~/.mycelium/foundry/logs` | Where `publish()` writes the JSONL. | Move to faster disk or a path you back up separately. |
| `db_path` | `~/.mycelium/foundry.db` | Where ingest drains decisions to. | Same idea as above. |
| `ingest_interval_seconds` | `0` | `0` = manual ingest (`mycelium foundry ingest` or implicit on `query_decisions`). `>0` = future: background drain loop. | Leave at 0 for now. |

## `[foundry.retention]`

Optional cleanup. `0` means unlimited.

| Key | Default | What it does |
|---|---|---|
| `max_rows` | `0` | Cap total rows; oldest deleted when exceeded. |
| `max_age_days` | `0` | Delete decisions older than N days. |

(Retention enforcement is a planned background pass — for now these are no-ops
unless you wire your own cleanup.)

## `[semantic]`

Optional semantic recall. Off by default and dependency-free when off. Set
`embed_url` to any OpenAI-compatible `/v1/embeddings` endpoint and `recall()`
becomes hybrid — keyword (FTS5) **plus** embedding similarity — so it can match
memories by meaning, not just shared words. Unset, recall behaves exactly as
before and no embedding calls are made. Run `mycelium backfill-vectors` once
after enabling; new memories are embedded automatically on save.

| Key | Default | What it does | When to change |
|---|---|---|---|
| `embed_url` | `""` | OpenAI-compatible embeddings endpoint. **Empty = semantic recall disabled.** | Set to e.g. `http://localhost:11434/v1/embeddings` (Ollama), LM Studio, llama.cpp `--embedding`, or a cloud provider. |
| `embed_model` | `"nomic-embed-text"` | Model name sent to the endpoint; also selects query/document prompt prefixes. | Match whatever your endpoint serves (`nomic-embed-text`, `embeddinggemma`, `bge-*`, `text-embedding-3-small`, ...). |
| `weight` | `10.0` | How strongly cosine similarity drives ranking relative to keyword coverage. | Lower toward `3` if semantic results crowd out exact keyword hits; raise for more meaning-driven ranking. |
| `top_k` | `15` | How many semantically-nearest memories are merged into the recall pool. | Raise for wider semantic reach; lower for tighter, faster recall. |
| `chunk_chars` | `1400` | Long memories are split into chunks of this size and mean-pooled into one stored vector. | Lower if your embedding model has a small context window. |
| `timeout_seconds` | `5` | Per embed HTTP call. Recall/save fall back gracefully if exceeded. | Raise on a slow/remote endpoint; the trade-off is slower recall/save. |

```toml
[semantic]
embed_url = "http://localhost:11434/v1/embeddings"
embed_model = "nomic-embed-text"
```

**Graceful by design:** if the endpoint is unreachable at runtime, recall
silently falls back to pure keyword search. `numpy` is used for the similarity
search only if it's already installed; otherwise a pure-Python path runs — it is
never a required dependency.

---

## Tuning by symptom

| Symptom | Knob to try |
|---|---|
| `recall()` keeps missing memories you remember | Lower `prune_threshold`, raise `decay_tau_days`, raise `recall_propagate` |
| `recall()` misses paraphrased / synonym queries (right idea, different words) | Enable semantic recall — set `[semantic] embed_url`, then `mycelium backfill-vectors` |
| `context()` output is overwhelming | Lower `hub_limit` |
| `save()` keeps complaining about duplicates I want anyway | Pass `force=True`, or revisit your save granularity |
| The DB is bloating | Raise `prune_threshold`, lower `decay_tau_days`, run `discover()` + `consolidate()` more often |
| `discover()` never makes useful keyword bridges | Populate `keyword_clusters` with terms from your domain |
| Foundry log dir filling up | Run `mycelium foundry ingest` periodically, then trim old `*.jsonl` |

## Inspecting the live config

```bash
mycelium config           # what got resolved, and from which file
```

If something doesn't behave the way the file says it should, this is the first
command to run.
