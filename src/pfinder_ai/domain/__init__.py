"""Vendor-independent domain types used by the investigation workflow.

Nothing in this package may import LangGraph, Codex, a database driver, or a
company SDK. Keeping this boundary strict makes provider adapters replaceable.
"""

