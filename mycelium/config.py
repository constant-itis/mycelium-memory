"""Config loader.

Resolution order (later wins): defaults -> config file -> env vars -> CLI args.
TOML via stdlib tomllib (Python 3.11+). All paths are ~ / $VAR expanded.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ----- defaults: every knob has a built-in fallback so zero-config works -----

DEFAULTS: dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8200,
        "transport": "stdio",
        "log_level": "info",
    },
    "storage": {
        "db_path": "~/.mycelium/memory.db",
        "backup_dir": "~/.mycelium/backups",
    },
    "memory": {
        "decay_tau_days": 30.0,
        "prune_threshold": 0.05,
        "auto_connect_limit": 5,
        "hub_limit": 15,
        "recall_propagate": 8,
        "consolidation_threshold": 10,
        "pinned_decay_floor": 0.5,
        "keyword_clusters": [],
        # --- recency surfacing (recent() / /wake) + prior-override salience ---
        "recent_window_days": 14,        # episodic horizon for recent() / /wake
        "recent_limit": 15,              # max memories in a digest (mirrors hub_limit)
        "recent_summary_chars": 140,     # per-line trim in the recent() text digest
        "wake_summary_chars": 200,       # per-item trim in the /wake JSON payload
        "contradicts_prior_boost": 0.25, # ranking bump for a stored fact that
                                         # conflicts with base knowledge; deliberately
                                         # > pin (0.1) so a learned exception beats a
                                         # confident-but-wrong default
    },
    "foundry": {
        "enabled": True,
        "log_dir": "~/.mycelium/foundry/logs",
        "db_path": "~/.mycelium/foundry.db",
        "ingest_interval_seconds": 0,
        "retention": {"max_rows": 0, "max_age_days": 0},
    },
    "semantic": {
        # Optional semantic-recall arm. Disabled while embed_url is empty —
        # recall stays pure-lexical (FTS5) and no embedding calls are made.
        "embed_url": "",                # any OpenAI-compatible /v1/embeddings
        "embed_model": "nomic-embed-text",
        "weight": 10.0,                 # cosine multiplier in recall scoring
        "top_k": 15,                    # semantic candidates merged into the pool
        "chunk_chars": 1400,            # long-content chunk size before mean-pool
        "timeout_seconds": 5,           # per embed call; keep recall/save snappy
    },
}


def _config_search_paths(explicit: str | None = None) -> list[Path]:
    """Where to look for config.toml, in order of precedence."""
    if explicit:
        return [Path(explicit).expanduser()]
    paths: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        paths.append(Path(xdg) / "mycelium" / "config.toml")
    paths.append(Path.home() / ".config" / "mycelium" / "config.toml")
    paths.append(Path.home() / ".mycelium" / "config.toml")
    return paths


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base (overlay wins on leaves)."""
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _coerce(target: Any, value: str) -> Any:
    """Coerce a string env var to the type of the existing default."""
    if isinstance(target, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(target, int):
        return int(value)
    if isinstance(target, float):
        return float(value)
    if isinstance(target, list):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


def _apply_env_overrides(cfg: dict, prefix: str = "MYCELIUM") -> dict:
    """MYCELIUM_SERVER_PORT=9000 -> cfg['server']['port'] = 9000.

    Walks the existing tree only — env vars naming unknown keys are ignored.
    Nested sections use double underscore (MYCELIUM_FOUNDRY__RETENTION__MAX_ROWS).
    """
    out = dict(cfg)

    def _walk(node: dict, path: list[str]):
        for k, v in node.items():
            new_path = path + [k]
            if isinstance(v, dict):
                _walk(v, new_path)
            else:
                env_key = f"{prefix}_" + "__".join(p.upper() for p in new_path)
                # also accept single-underscore for top-level keys (more readable)
                env_key_alt = f"{prefix}_" + "_".join(p.upper() for p in new_path)
                raw = os.environ.get(env_key) or os.environ.get(env_key_alt)
                if raw is not None:
                    # walk into out and set
                    cursor = out
                    for p in new_path[:-1]:
                        cursor = cursor[p]
                    cursor[new_path[-1]] = _coerce(v, raw)

    _walk(cfg, [])
    return out


def _expand_paths(cfg: dict) -> dict:
    """Expand ~ and $VAR in known path keys."""
    path_keys = {
        ("storage", "db_path"),
        ("storage", "backup_dir"),
        ("foundry", "log_dir"),
        ("foundry", "db_path"),
    }
    out = dict(cfg)
    for section, key in path_keys:
        if section in out and key in out[section]:
            raw = out[section][key]
            if isinstance(raw, str):
                out[section][key] = str(Path(os.path.expandvars(raw)).expanduser())
    return out


@dataclass
class Config:
    server: dict
    storage: dict
    memory: dict
    foundry: dict
    semantic: dict
    source: str  # "defaults" | "<path-to-toml>"

    @property
    def semantic_enabled(self) -> bool:
        return bool(self.semantic.get("embed_url"))

    @property
    def db_path(self) -> Path:
        return Path(self.storage["db_path"])

    @property
    def foundry_db_path(self) -> Path:
        return Path(self.foundry["db_path"])

    @property
    def foundry_log_dir(self) -> Path:
        return Path(self.foundry["log_dir"])

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "storage": self.storage,
            "memory": self.memory,
            "foundry": self.foundry,
            "semantic": self.semantic,
        }


def load(config_path: str | None = None) -> Config:
    """Load config from disk + env, layered over defaults.

    Set MYCELIUM_CONFIG=/path/to/config.toml to override search paths.
    """
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    # deep-copy nested dicts
    cfg["foundry"]["retention"] = dict(DEFAULTS["foundry"]["retention"])
    cfg["semantic"] = dict(DEFAULTS["semantic"])

    explicit = config_path or os.environ.get("MYCELIUM_CONFIG")
    found_path: Path | None = None
    for path in _config_search_paths(explicit):
        if path.is_file():
            with path.open("rb") as f:
                file_cfg = tomllib.load(f)
            cfg = _deep_merge(cfg, file_cfg)
            found_path = path
            break

    cfg = _apply_env_overrides(cfg)
    cfg = _expand_paths(cfg)

    return Config(
        server=cfg["server"],
        storage=cfg["storage"],
        memory=cfg["memory"],
        foundry=cfg["foundry"],
        semantic=cfg["semantic"],
        source=str(found_path) if found_path else "defaults",
    )
