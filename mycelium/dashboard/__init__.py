"""Read-only web graph explorer for a Mycelium memory database.

Stdlib only (http.server + sqlite3) so it adds no dependencies to the package.
Opens the database in read-only mode and never writes. Serves a small JSON API
plus the static single-page app under ./static.

Run it with:  ``mycelium dash``  (see mycelium.cli), or programmatically via
``mycelium.dashboard.serve(config)``.
"""
from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

STATIC_DIR = Path(__file__).parent / "static"

# normalize NULL/'' project -> '(none)' inside SQL
PROJ = "CASE WHEN project IS NULL OR project='' THEN '(none)' ELSE project END"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".woff2": "font/woff2",
}

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


class _DB:
    """Opens the memory database read-only. Raises if it does not exist."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn


def _parse_csv(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


# --------------------------------------------------------------------------- #
# query layer — every function takes an open connection and returns plain data
# --------------------------------------------------------------------------- #

def _stats(conn):
    def _count(sql):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    return {
        "memories": _count("SELECT COUNT(*) FROM memories"),
        "connections": _count("SELECT COUNT(*) FROM connections"),
        "vectors": _count("SELECT COUNT(*) FROM memory_vectors"),
        "recall_log": _count("SELECT COUNT(*) FROM recall_log"),
        "projects": _count("SELECT COUNT(DISTINCT project) FROM memories"),
        "pinned": _count("SELECT COUNT(*) FROM memories WHERE pinned=1"),
    }


def _projects(conn):
    rows = conn.execute(
        f"SELECT {PROJ} AS project, COUNT(*) AS count FROM memories "
        "GROUP BY project ORDER BY count DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _graph_projects(conn):
    node_rows = conn.execute(f"""
        SELECT {PROJ} AS project, COUNT(*) AS count,
               SUM(access_count) AS access, SUM(pinned) AS pinned
        FROM memories GROUP BY project
    """).fetchall()
    edge_rows = conn.execute(f"""
        WITH cp AS (
          SELECT
            CASE WHEN a.project IS NULL OR a.project='' THEN '(none)' ELSE a.project END AS pa,
            CASE WHEN b.project IS NULL OR b.project='' THEN '(none)' ELSE b.project END AS pb,
            c.strength AS s
          FROM connections c
          JOIN memories a ON a.id = c.source
          JOIN memories b ON b.id = c.target
          WHERE c.source < c.target
        )
        SELECT CASE WHEN pa < pb THEN pa ELSE pb END AS source,
               CASE WHEN pa < pb THEN pb ELSE pa END AS target,
               COUNT(*) AS count, SUM(s) AS weight
        FROM cp WHERE pa <> pb GROUP BY source, target
    """).fetchall()
    internal_rows = conn.execute(f"""
        WITH cp AS (
          SELECT
            CASE WHEN a.project IS NULL OR a.project='' THEN '(none)' ELSE a.project END AS pa,
            CASE WHEN b.project IS NULL OR b.project='' THEN '(none)' ELSE b.project END AS pb
          FROM connections c
          JOIN memories a ON a.id = c.source
          JOIN memories b ON b.id = c.target
          WHERE c.source < c.target
        )
        SELECT pa AS project, COUNT(*) AS internal FROM cp WHERE pa = pb GROUP BY pa
    """).fetchall()
    internal = {r["project"]: r["internal"] for r in internal_rows}
    nodes = [{
        "id": r["project"], "kind": "project", "label": r["project"],
        "count": r["count"], "access": r["access"] or 0, "pinned": r["pinned"] or 0,
        "internal": internal.get(r["project"], 0),
    } for r in node_rows]
    edges = [{
        "source": r["source"], "target": r["target"], "count": r["count"],
        "weight": r["weight"], "strength": (r["weight"] / r["count"]) if r["count"] else 0,
    } for r in edge_rows]
    return {"level": "projects", "nodes": nodes, "edges": edges}


def _graph_project(conn, name):
    node_rows = conn.execute(f"""
        SELECT id, content, {PROJ} AS project, tier, confidence,
               access_count, pinned, last_accessed, created, source_type
        FROM memories WHERE {PROJ} = ?
        ORDER BY access_count DESC, id ASC
    """, (name,)).fetchall()
    node_ids = [r["id"] for r in node_rows]
    edges = []
    if node_ids:
        ids_csv = ",".join(str(i) for i in node_ids)
        edge_rows = conn.execute(f"""
            SELECT source, target, strength, co_access_count FROM connections
            WHERE source < target AND source IN ({ids_csv}) AND target IN ({ids_csv})
        """).fetchall()
        edges = [{"source": r["source"], "target": r["target"],
                  "strength": r["strength"], "co_access_count": r["co_access_count"]}
                 for r in edge_rows]
    nodes = []
    for r in node_rows:
        content = r["content"] or ""
        nodes.append({
            "id": r["id"], "kind": "memory", "label": content.split("\n", 1)[0][:80],
            "content_preview": content[:240], "project": r["project"], "tier": r["tier"],
            "confidence": r["confidence"], "access_count": r["access_count"],
            "pinned": bool(r["pinned"]), "last_accessed": r["last_accessed"], "created": r["created"],
        })
    return {"level": "project", "project": name, "nodes": nodes, "edges": edges}


def _graph_ego(conn, mid, depth_limit=40):
    center = conn.execute(
        f"SELECT id FROM memories WHERE id=?", (mid,)).fetchone()
    if not center:
        return None
    nbr_rows = conn.execute("""
        SELECT CASE WHEN source=? THEN target ELSE source END AS nid, MAX(strength) AS strength
        FROM connections WHERE source=? OR target=?
        GROUP BY nid ORDER BY strength DESC LIMIT ?
    """, (mid, mid, mid, depth_limit)).fetchall()
    ids = [mid] + [r["nid"] for r in nbr_rows]
    ids_csv = ",".join(str(i) for i in ids)
    info_rows = conn.execute(f"""
        SELECT id, content, {PROJ} AS project, access_count, pinned, confidence, tier
        FROM memories WHERE id IN ({ids_csv})
    """).fetchall()
    edge_rows = conn.execute(f"""
        SELECT source, target, strength, co_access_count FROM connections
        WHERE source < target AND source IN ({ids_csv}) AND target IN ({ids_csv})
    """).fetchall()
    nodes = []
    for r in info_rows:
        content = r["content"] or ""
        nodes.append({
            "id": r["id"], "kind": "memory", "label": content.split("\n", 1)[0][:80],
            "content_preview": content[:240], "project": r["project"],
            "access_count": r["access_count"], "pinned": bool(r["pinned"]),
            "confidence": r["confidence"], "tier": r["tier"], "is_center": r["id"] == mid,
        })
    edges = [{"source": r["source"], "target": r["target"],
              "strength": r["strength"], "co_access_count": r["co_access_count"]}
             for r in edge_rows]
    return {"level": "ego", "center": mid, "nodes": nodes, "edges": edges}


def _graph_full(conn, min_strength=0.5):
    node_rows = conn.execute(f"""
        SELECT id, content, {PROJ} AS project, access_count, pinned FROM memories
    """).fetchall()
    edge_rows = conn.execute("""
        SELECT source, target, strength FROM connections
        WHERE source < target AND strength >= ?
    """, (min_strength,)).fetchall()
    nodes = [{
        "id": r["id"], "project": r["project"],
        "label": (r["content"] or "").split("\n", 1)[0][:70],
        "access_count": r["access_count"], "pinned": bool(r["pinned"]),
    } for r in node_rows]
    edges = [{"source": r["source"], "target": r["target"], "strength": r["strength"]}
             for r in edge_rows]
    return {"nodes": nodes, "edges": edges}


def _memory_detail(conn, mid):
    m = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
    if not m:
        return None
    neighbors = conn.execute("""
        SELECT m.id, m.content, m.project, c.strength, c.co_access_count
        FROM connections c JOIN memories m ON m.id = c.target
        WHERE c.source = ? ORDER BY c.strength DESC LIMIT 25
    """, (mid,)).fetchall()
    try:
        agents = conn.execute("""
            SELECT agent, access_count, last_accessed FROM agent_access
            WHERE memory_id=? ORDER BY access_count DESC
        """, (mid,)).fetchall()
    except sqlite3.OperationalError:
        agents = []
    return {"memory": dict(m),
            "neighbors": [dict(n) for n in neighbors],
            "agents": [dict(a) for a in agents]}


def _search(conn, q):
    if not q:
        return {"results": []}
    try:
        rows = conn.execute("""
            SELECT m.id, m.content, m.project, m.access_count
            FROM memories_fts f JOIN memories m ON m.id = f.rowid
            WHERE memories_fts MATCH ? ORDER BY rank LIMIT 50
        """, (q,)).fetchall()
    except sqlite3.OperationalError:
        like = f"%{q}%"
        rows = conn.execute("""
            SELECT id, content, project, access_count FROM memories
            WHERE content LIKE ? ORDER BY access_count DESC LIMIT 50
        """, (like,)).fetchall()
    return {"results": [
        {"id": r["id"], "preview": (r["content"] or "")[:160],
         "project": r["project"], "access_count": r["access_count"]}
        for r in rows]}


def _recent(conn):
    try:
        rows = conn.execute("""
            SELECT id, query, project, timestamp, results
            FROM recall_log ORDER BY id DESC LIMIT 40
        """).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["results"] = json.loads(d["results"])
        except Exception:
            d["results"] = []
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

def _make_handler(db: _DB):

    class Handler(BaseHTTPRequestHandler):
        server_version = "mycelium-dash"

        def log_message(self, *args):  # quiet by default
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for k, v in _NO_CACHE.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel):
            # resolve safely inside STATIC_DIR (no traversal)
            target = (STATIC_DIR / rel).resolve()
            try:
                target.relative_to(STATIC_DIR.resolve())
            except ValueError:
                return self._send_json({"error": "forbidden"}, 403)
            if not target.is_file():
                return self._send_json({"error": "not found"}, 404)
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            if target.suffix in (".html",):
                for k, v in _NO_CACHE.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            try:
                if path == "/" or path == "/index.html":
                    return self._send_static("index.html")
                if path.startswith("/static/"):
                    return self._send_static(path[len("/static/"):])
                if path.startswith("/api/"):
                    return self._handle_api(path, qs)
                return self._send_json({"error": "not found"}, 404)
            except FileNotFoundError:
                return self._send_json(
                    {"error": "database not found",
                     "detail": f"no memory database at {db.db_path} — "
                               "save some memories first, or set storage.db_path"}, 503)
            except BrokenPipeError:
                pass
            except Exception as e:  # never crash the server on a bad query
                return self._send_json({"error": str(e)}, 500)

        def _handle_api(self, path, qs):
            conn = db.connect()
            try:
                if path == "/api/stats":
                    return self._send_json(_stats(conn))
                if path == "/api/projects":
                    return self._send_json(_projects(conn))
                if path == "/api/graph/projects":
                    return self._send_json(_graph_projects(conn))
                if path == "/api/graph/full":
                    ms = float(qs.get("min_strength", ["0.5"])[0])
                    return self._send_json(_graph_full(conn, ms))
                if path.startswith("/api/graph/project/"):
                    name = unquote(path[len("/api/graph/project/"):])
                    return self._send_json(_graph_project(conn, name))
                if path.startswith("/api/graph/ego/"):
                    mid = int(path[len("/api/graph/ego/"):])
                    res = _graph_ego(conn, mid)
                    return self._send_json(res or {"error": "not found"}, 200 if res else 404)
                if path.startswith("/api/memory/"):
                    mid = int(path[len("/api/memory/"):])
                    res = _memory_detail(conn, mid)
                    return self._send_json(res or {"error": "not found"}, 200 if res else 404)
                if path == "/api/search":
                    return self._send_json(_search(conn, (qs.get("q", [""])[0]).strip()))
                if path == "/api/recent":
                    return self._send_json(_recent(conn))
                return self._send_json({"error": "not found"}, 404)
            finally:
                conn.close()

    return Handler


def serve(config, host: str | None = None, port: int | None = None) -> None:
    """Start the read-only dashboard HTTP server (blocking).

    ``config`` is a mycelium.config.Config. host/port override the
    ``[dashboard]`` config section.
    """
    dash = getattr(config, "dashboard", None) or {}
    host = host or dash.get("host", "127.0.0.1")
    port = int(port or dash.get("port", 8600))
    db = _DB(config.db_path)

    httpd = ThreadingHTTPServer((host, port), _make_handler(db))
    print(f"mycelium dashboard  ->  http://{host}:{port}")
    print(f"reading (read-only): {config.db_path}")
    if not db.db_path.exists():
        print(f"warning: {db.db_path} does not exist yet — save some memories first.")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        httpd.server_close()
