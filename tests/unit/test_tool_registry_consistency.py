"""Tests for TOOL_DEFINITIONS / dispatcher / TOOL_SPECS registry consistency.

Prevents regressions where a tool is defined but not dispatched, or dispatched
without a resource gate spec (doc 13).
"""

from __future__ import annotations

from paperforge.orchestrator.tools import TOOL_DEFINITIONS, TOOL_HANDLERS
from paperforge.orchestrator.workspace import (
    WorkspaceState,
    check_tool_prerequisites,
    TOOL_SPECS,
)

# Control-only tools don't need a resource gate spec.
CONTROL_TOOLS = {"finish"}


def test_tool_registry_consistency():
    definitions = {definition.name for definition in TOOL_DEFINITIONS}
    dispatchers = set(TOOL_HANDLERS)
    assert definitions == dispatchers
    resource_tools = definitions - CONTROL_TOOLS
    assert resource_tools <= set(TOOL_SPECS)


def test_unknown_tool_fails_closed():
    allowed, missing = check_tool_prerequisites("does_not_exist", WorkspaceState())
    assert allowed is False
    assert "unknown_tool" in missing
