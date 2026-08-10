"""Tests for Verification V3 hard gates (doc 24)."""

from __future__ import annotations

from paperforge.schemas.verification import (
    VerificationGates,
    VerificationReport,
)


def test_technical_ready_requires_all_hard_gates():
    g = VerificationGates(
        workspace_ok=True,
        typecheck_ok=True,
        build_ok=True,
        security_ok=True,
    )
    assert g.technical_ready is True

    # A type error (hard) must not be overridden by other ok gates.
    g2 = VerificationGates(
        workspace_ok=True,
        typecheck_ok=False,
        build_ok=True,
        security_ok=True,
    )
    assert g2.technical_ready is False

    g3 = VerificationGates(
        workspace_ok=True,
        typecheck_ok=True,
        build_ok=False,
        security_ok=True,
    )
    assert g3.technical_ready is False


def test_preview_allowed_requires_workspace_and_build():
    g = VerificationGates(
        workspace_ok=True,
        typecheck_ok=False,
        build_ok=True,
        security_ok=False,
    )
    assert g.preview_allowed is True  # debug preview still allowed


def test_product_ready_requires_runtime_and_acceptance():
    g = VerificationGates(
        workspace_ok=True,
        typecheck_ok=True,
        build_ok=True,
        security_ok=True,
        runtime_ok=True,
        acceptance_ok=True,
    )
    assert g.product_ready is True

    # must-criterion failure (acceptance_ok=False) must block product_ready.
    g2 = g.model_copy(update={"acceptance_ok": False})
    assert g2.product_ready is False

    # unknown runtime (None) blocks product_ready.
    g3 = g.model_copy(update={"runtime_ok": None})
    assert g3.product_ready is False


def test_report_carries_gates_and_readiness_fields():
    report = VerificationReport(
        app_id="app_x",
        gates=VerificationGates(
            workspace_ok=True,
            typecheck_ok=False,
            build_ok=True,
            security_ok=True,
        ),
    )
    assert report.gates.technical_ready is False
    assert report.technical_ready is False
