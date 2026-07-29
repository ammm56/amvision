"""SAM3 节点单元测试使用的 Workflow Model Session 替身。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from custom_nodes.sam3_segment_nodes.backend.runtime.access import (
    get_or_create_sam3_interactive_runtime_session,
    get_or_create_sam3_semantic_runtime_session,
)


@dataclass
class _TestWorkflowSession:
    interactive: object | None = None
    semantic: object | None = None

    def require_interactive(self) -> object:
        assert self.interactive is not None
        return self.interactive

    def require_semantic(self) -> object:
        assert self.semantic is not None
        return self.semantic


@dataclass
class _TestLease:
    session_factory: Callable[[], _TestWorkflowSession]

    @contextmanager
    def locked_session(self, *, capability: str) -> Iterator[_TestWorkflowSession]:
        del capability
        yield self.session_factory()


def patch_interactive_session(monkeypatch, module, session: object) -> None:
    """让一个节点模块通过新 lease 边界使用指定 interactive session。"""

    lease = _TestLease(lambda: _TestWorkflowSession(interactive=session))
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def patch_semantic_session(monkeypatch, module, session: object) -> None:
    """让一个节点模块通过新 lease 边界使用指定 semantic session。"""

    lease = _TestLease(lambda: _TestWorkflowSession(semantic=session))
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def patch_real_interactive_session(monkeypatch, module) -> None:
    """为 project-native smoke 测试构造真实 interactive session lease。"""

    lease = _TestLease(
        lambda: _TestWorkflowSession(
            interactive=get_or_create_sam3_interactive_runtime_session(
                model_asset_id="sam3/default",
                device="cpu",
                precision="fp32",
            )
        )
    )
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def patch_real_semantic_session(monkeypatch, module) -> None:
    """为 project-native smoke 测试构造真实 semantic session lease。"""

    lease = _TestLease(
        lambda: _TestWorkflowSession(
            semantic=get_or_create_sam3_semantic_runtime_session(
                model_asset_id="sam3/default",
                device="cpu",
                precision="fp32",
            )
        )
    )
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )
