"""Requirement registry: chỉ Verdict engine được chuyển yêu cầu sang DECIDED."""

from __future__ import annotations

from pathlib import Path

import pytest

from rfcv.evidence.registry import RequirementRegistry, State, TransitionError


def test_registry_only_verdict_engine_decides(tmp_path: Path) -> None:
    reg = RequirementRegistry(tmp_path / "registry.db")
    reg.add("TLS13-0042", {"rbs": "..."}, actor="rfc_gate")
    reg.transition("TLS13-0042", State.SPECIFIED, "oracle_compiler")
    reg.transition("TLS13-0042", State.INVESTIGATING, "execution_loop")
    with pytest.raises(TransitionError, match="Verdict engine"):
        reg.transition("TLS13-0042", State.DECIDED, "planner")
    reg.transition("TLS13-0042", State.DECIDED, "verdict_engine")
    assert reg.state("TLS13-0042") is State.DECIDED
    with pytest.raises(TransitionError):
        reg.transition("TLS13-0042", State.SPECIFIED, "auditor")
