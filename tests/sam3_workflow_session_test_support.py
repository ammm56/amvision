"""SAM3 节点单元测试使用的 Workflow Model Session 替身。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode
from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3InteractiveRuntimeSession,
    Sam3SemanticRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    resolve_sam3_pretrained_variant,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    Sam3WorkflowModelSessionProvider,
)


@dataclass
class _TestWorkflowSession:
    interactive: object | None = None
    semantic: object | None = None
    multiplex: object | None = None

    def require_interactive(self) -> object:
        assert self.interactive is not None
        return self.interactive

    def require_semantic(self) -> object:
        assert self.semantic is not None
        return self.semantic

    def require_multiplex(self) -> object:
        assert self.multiplex is not None
        return self.multiplex


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


def patch_video_sessions(
    monkeypatch,
    module,
    *,
    interactive: object,
    multiplex: object,
    semantic: object | None = None,
) -> None:
    """让视频节点同时取得首帧模型和 Multiplex propagation session。"""

    lease = _TestLease(
        lambda: _TestWorkflowSession(
            interactive=interactive,
            semantic=semantic,
            multiplex=multiplex,
        )
    )
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def patch_real_video_workflow_session(
    monkeypatch,
    module,
    session: Sam3WorkflowModelSession,
) -> None:
    """让显式 integration 测试使用真实 AppRuntime SAM3 会话。"""

    lease = _TestLease(lambda: session)
    monkeypatch.setattr(
        module,
        "resolve_sam3_session_lease",
        lambda _request, *, capability: lease,
    )


def build_real_video_workflow_session(
    *,
    device_name: str,
    precision: str,
    include_semantic: bool,
) -> Sam3WorkflowModelSession:
    """按正式 provider 边界构造一次可复用的视频模型会话。"""

    consumer_node_type_ids = ["custom.sam3.video-interactive-segment"]
    if include_semantic:
        consumer_node_type_ids.append("custom.sam3.video-semantic-segment")
    load_result = Sam3WorkflowModelSessionProvider().load(
        loader_node=WorkflowGraphNode(
            node_id="sam3-load-checkpoint",
            node_type_id="custom.sam3.load-checkpoint",
            parameters={
                "model_asset_id": "sam3/default",
                "device": device_name,
                "precision": precision,
            },
        ),
        consumer_node_type_ids=tuple(consumer_node_type_ids),
        runtime_context=object(),
    )
    session = load_result.session
    if not isinstance(session, Sam3WorkflowModelSession):
        raise AssertionError("SAM3 provider 没有返回 Workflow Model Session")
    return session


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
