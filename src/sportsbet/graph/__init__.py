"""Agent graph package.

Provides Pydantic v2 I/O models and LangGraph runtime factories for the agent layer.
All downstream agents (Phase 3+) code against the typed contracts defined here.

Primary entry point: create_graph() returns a compiled CompiledStateGraph
ready for ainvoke(initial_state) calls.
"""
from sportsbet.graph.graph import create_graph, create_graph_with_sqlite

__all__ = ["create_graph", "create_graph_with_sqlite"]
