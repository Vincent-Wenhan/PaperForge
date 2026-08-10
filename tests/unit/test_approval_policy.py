"""Risk-based approval policy tests (doc 17)."""

from __future__ import annotations

import pytest

from paperforge.orchestrator.approvals import (
    ApprovalMode,
    ApprovalPolicy,
    ToolSpec,
)


def test_always_requires_non_read():
    policy = ApprovalPolicy(mode=ApprovalMode.ALWAYS)
    assert not policy.requires(ToolSpec(name="inspect_workspace", risk="read"))
    assert policy.requires(ToolSpec(name="apply_workspace_patch", risk="workspace_write"))
    assert policy.requires(ToolSpec(name="run_in_sandbox", risk="sandbox_exec"))


def test_manual_requires_nothing():
    policy = ApprovalPolicy(mode=ApprovalMode.MANUAL)
    assert not policy.requires(ToolSpec(name="apply_workspace_patch", risk="workspace_write"))
    assert not policy.requires(ToolSpec(name="run_in_sandbox", risk="sandbox_exec"))
    assert not policy.requires(ToolSpec(name="delete_app", risk="destructive"))


def test_trust_workspace_skips_internal_edits_and_prompts_on_network():
    policy = ApprovalPolicy()  # default TRUST_WORKSPACE, isolated
    assert not policy.requires(ToolSpec(name="read_workspace_file", risk="read"))
    assert not policy.requires(ToolSpec(name="apply_workspace_patch", risk="workspace_write"))
    assert not policy.requires(ToolSpec(name="run_in_sandbox", risk="sandbox_exec"))
    assert policy.requires(ToolSpec(name="publish_result", risk="network"))
    assert policy.requires(ToolSpec(name="delete_app", risk="destructive"))


def test_trust_workspace_untrusted_sandbox_prompts_on_exec():
    policy = ApprovalPolicy(workspace_isolated=False)
    assert not policy.requires(ToolSpec(name="apply_workspace_patch", risk="workspace_write"))
    assert policy.requires(ToolSpec(name="run_in_sandbox", risk="sandbox_exec"))
