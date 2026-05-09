"""Foundry — behavioral memory card.

Append-only decision log. Every recorded decision becomes a row that can be
queried later for pattern analysis, training-data extraction, or audit.

Usage:
    from mycelium.foundry import publish
    publish("model_routing", agent="my-agent", decision_made="use-cheaper-tier",
            input_features={"prompt_tokens": 412})
"""
from .publisher import publish
from .schema import init_schema

__all__ = ["publish", "init_schema"]
