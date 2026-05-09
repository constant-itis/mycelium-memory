"""mycelium CLI."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import config as _config


def _cmd_serve(args: argparse.Namespace) -> int:
    from . import server
    if args.config:
        server.set_config(_config.load(args.config))
    server.serve(transport=args.transport, host=args.host, port=args.port)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Copy the bundled config.example.toml to a user-writable path."""
    target = Path(args.path).expanduser() if args.path else Path.home() / ".mycelium" / "config.toml"
    if target.exists() and not args.force:
        print(f"refuse: {target} already exists (pass --force to overwrite)", file=sys.stderr)
        return 1
    # find the bundled example next to the package, or in the repo root
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "config.example.toml",
        Path.cwd() / "config.example.toml",
    ]
    src = next((p for p in candidates if p.is_file()), None)
    if not src:
        print("could not locate config.example.toml in package", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, target)
    print(f"wrote {target}")
    return 0


def _cmd_maintain(args: argparse.Namespace) -> int:
    from . import maintain as _maintain
    cfg = _config.load(args.config)
    backup_dir = Path(cfg.storage["backup_dir"]).expanduser() if cfg.storage.get("backup_dir") else None
    result = _maintain.run_maintenance(
        cfg.db_path,
        execute=args.execute,
        recent_days=args.recent_days,
        confidence_floor=args.confidence_floor,
        backup_dir=backup_dir,
        no_backup=args.no_backup,
    )
    print(_maintain.format_report(result))
    return 0 if "error" not in result else 1


def _cmd_foundry_ingest(args: argparse.Namespace) -> int:
    from .foundry import ingest as foundry_ingest
    cfg = _config.load(args.config)
    n = foundry_ingest.drain_all(cfg.foundry_db_path, cfg.foundry_log_dir)
    print(f"ingested {n} decision rows into {cfg.foundry_db_path}")
    return 0


def _cmd_foundry_query(args: argparse.Namespace) -> int:
    from .foundry import ingest as foundry_ingest
    cfg = _config.load(args.config)
    rows = foundry_ingest.query(
        cfg.foundry_db_path,
        agent=args.agent,
        decision_point=args.decision_point,
        failure_class=args.failure_class,
        since_iso=args.since,
        limit=args.limit,
    )
    if not rows:
        print("no decisions match.")
        return 0
    for r in rows:
        head = f"[{r['ts']}] {r['agent']}/{r['decision_point']}: {r['decision_made']}"
        print(head)
        if r.get("failure_class"):
            print(f"    failure: {r['failure_class']} — {r.get('failure_detail') or ''}")
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    cfg = _config.load(args.config)
    print(f"# loaded from: {cfg.source}")
    import json
    print(json.dumps(cfg.to_dict(), indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mycelium", description="Mycelium memory MCP server")
    p.add_argument("--config", help="path to config.toml (overrides search paths)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the MCP server")
    s.add_argument("--transport", choices=["stdio", "http"], help="override config")
    s.add_argument("--host", help="override config (http only)")
    s.add_argument("--port", type=int, help="override config (http only)")
    s.set_defaults(func=_cmd_serve)

    i = sub.add_parser("init", help="copy config.example.toml to a writable path")
    i.add_argument("--path", help="target path (default: ~/.mycelium/config.toml)")
    i.add_argument("--force", action="store_true", help="overwrite if exists")
    i.set_defaults(func=_cmd_init)

    cfg_cmd = sub.add_parser("config", help="print effective config")
    cfg_cmd.set_defaults(func=_cmd_config)

    m = sub.add_parser("maintain", help="snapshot + cold-mark + orphan rescue (dry-run by default)")
    m.add_argument("--execute", action="store_true", help="apply the plan (default is dry-run)")
    m.add_argument("--recent-days", type=int, default=7,
                   help="protect anything accessed within the last N days (default: 7)")
    m.add_argument("--confidence-floor", type=float, default=0.8,
                   help="protect anything with confidence >= this (default: 0.8)")
    m.add_argument("--no-backup", action="store_true",
                   help="skip the snapshot copy (use only if you back up elsewhere)")
    m.set_defaults(func=_cmd_maintain)

    f = sub.add_parser("foundry", help="behavioral memory operations")
    fsub = f.add_subparsers(dest="foundry_cmd", required=True)

    fi = fsub.add_parser("ingest", help="drain JSONL logs into the foundry DB")
    fi.set_defaults(func=_cmd_foundry_ingest)

    fq = fsub.add_parser("query", help="query foundry decisions")
    fq.add_argument("--agent")
    fq.add_argument("--decision-point")
    fq.add_argument("--failure-class")
    fq.add_argument("--since", help="ISO-8601 timestamp")
    fq.add_argument("--limit", type=int, default=50)
    fq.set_defaults(func=_cmd_foundry_query)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
