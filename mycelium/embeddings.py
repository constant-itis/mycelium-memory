"""Optional embedding client for semantic recall.

Pure standard library — no third-party deps. Talks to any OpenAI-compatible
``/v1/embeddings`` endpoint (Ollama, LM Studio, llama.cpp, OpenAI, ...). This
module is only imported/used when ``[semantic] embed_url`` is configured;
mycelium's core stays dependency-free and behaves exactly as before when it is
unset.

Cosine uses numpy *opportunistically* if it happens to be installed (faster on
large corpora), but falls back to a pure-Python dot product — numpy is never
required.
"""
from __future__ import annotations

import json
import math
import struct
import urllib.request

# Asymmetric query/document prompts matter for some models and not others.
# Keyed by case-insensitive substring of the model name; unknown -> no prefix.
#   value = (document_prefix, query_prefix)
_PREFIXES = {
    "nomic": ("search_document: ", "search_query: "),
    "embeddinggemma": ("title: none | text: ", "task: search result | query: "),
    "gemma": ("title: none | text: ", "task: search result | query: "),
    "e5": ("passage: ", "query: "),
}


def _prefixes(model: str) -> tuple[str, str]:
    m = (model or "").lower()
    for key, pair in _PREFIXES.items():
        if key in m:
            return pair
    return ("", "")


def _post(url: str, model: str, inputs: list[str], timeout: float) -> list[list[float]]:
    body = json.dumps({"model": model, "input": inputs}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())["data"]
    # Preserve input order regardless of how the server returns them.
    return [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]


def _chunks(text: str, n: int) -> list[str]:
    text = (text or "").strip()
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


def _normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _mean(vecs: list[list[float]]) -> list[float]:
    dim = len(vecs[0])
    out = [0.0] * dim
    for v in vecs:
        for i, x in enumerate(v):
            out[i] += x
    return [x / len(vecs) for x in out]


def embed_document(text, *, url, model, chunk_chars=1400, timeout=5):
    """One L2-normalized vector for a memory. Long content is chunked and the
    per-chunk vectors are mean-pooled (keeps inputs under model context limits)."""
    doc_prefix, _ = _prefixes(model)
    chunks = _chunks(text, chunk_chars)
    vecs = [_normalize(v) for v in _post(url, model, [doc_prefix + c for c in chunks], timeout)]
    return _normalize(_mean(vecs)) if len(vecs) > 1 else vecs[0]


def embed_query(text, *, url, model, timeout=5):
    """One L2-normalized query vector."""
    _, query_prefix = _prefixes(model)
    return _normalize(_post(url, model, [query_prefix + text], timeout)[0])


def to_blob(vec: list[float]) -> bytes:
    """Serialize a vector to a compact little-endian float32 BLOB."""
    return struct.pack(f"<{len(vec)}f", *vec)


def from_blob(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine_sims(qvec, rows) -> dict:
    """{memory_id: cosine} for rows of (memory_id, blob).

    Stored vectors and ``qvec`` are L2-normalized, so a dot product is the
    cosine. Uses numpy if available (and the buffer is uniform), else pure
    Python — numpy is an optional speedup, not a requirement.
    """
    rows = list(rows)
    if not rows:
        return {}
    try:
        import numpy as np

        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype="float32").reshape(
            len(rows), -1
        )
        sims = mat @ np.asarray(qvec, dtype="float32")
        return {rows[i][0]: float(sims[i]) for i in range(len(rows))}
    except Exception:
        return {mid: sum(a * b for a, b in zip(qvec, from_blob(blob))) for mid, blob in rows}


def healthy(url, model, timeout=5) -> bool:
    """True if the embedding endpoint answers — used for graceful fallback."""
    try:
        _post(url, model, ["healthcheck"], timeout)
        return True
    except Exception:
        return False
