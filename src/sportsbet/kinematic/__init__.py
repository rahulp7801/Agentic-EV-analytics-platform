"""Kinematic Agent subpackage — NGS tracking queries and geometric matchup signals.

Never imported by graph/; graph/agents.py imports from here (one-way dependency).
This package is the pure data layer: KinematicParams, KinematicAnalysis models,
NGS season availability guard, and the matchup query executor.

Plan 02 wraps these primitives in a make_kinematic_agent(pool) closure factory
and wires them as a LangGraph node in graph/agents.py.
"""
