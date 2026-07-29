"""SAM3 节点单元测试使用的 Workflow Model Session 替身。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3InteractiveRuntimeSession,
    Sam3SemanticRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    resolve_sam3_pretrained_variant,
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
            interactive=_build_real_interactive_session(
                model_asset_id="sam3/default",
                device_name="cpu",
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
            semantic=build_real_semantic_session(
                model_asset_id="sam3/default",
                device_name="cpu",
                precision="fp32",
            )
        )
    )
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def _build_real_interactive_session(
    *,
    model_asset_id: str,
    device_name: str,
    precision: str,
) -> Sam3InteractiveRuntimeSession:
    """按 AppRuntime 生命周期的构造方式创建真实 interactive session。"""

    variant = resolve_sam3_pretrained_variant(model_asset_id=model_asset_id)
    return Sam3InteractiveRuntimeSession(
        checkpoint_path=variant.checkpoint_path,
        model_asset_id=variant.model_asset_id,
        architecture_id=variant.architecture_id,
        requested_device_name=device_name,
        precision=precision,
    )


def build_real_semantic_session(
    *,
    model_asset_id: str,
    device_name: str,
    precision: str,
) -> Sam3SemanticRuntimeSession:
    """按 AppRuntime 生命周期的构造方式创建真实 semantic session。"""

    variant = resolve_sam3_pretrained_variant(model_asset_id=model_asset_id)
    return Sam3SemanticRuntimeSession(
        checkpoint_path=variant.checkpoint_path,
        model_asset_id=variant.model_asset_id,
        architecture_id=variant.architecture_id,
        requested_device_name=device_name,
        precision=precision,
    )
