"""Agent graph package.

Provides Pydantic v2 I/O models and LangGraph node stubs for the agent layer.
All downstream agents (Phase 3+) code against the typed contracts defined here.

Primary entry point: create_graph() returns a compiled CompiledStateGraph
ready for ainvoke(initial_state) calls.
"""
from sportsbet.graph.graph import create_graph

__all__ = ["create_graph"]
