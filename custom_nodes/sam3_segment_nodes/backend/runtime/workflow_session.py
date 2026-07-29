"""SAM3 接入通用 Workflow Model Session 生命周期。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.model_sessions import (
    WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
    WorkflowModelSessionLoadResult,
    WorkflowModelSessionManager,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3InteractiveRuntimeSession,
    Sam3SemanticRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    normalize_device,
    normalize_model_asset_id,
    normalize_precision,
    resolve_sam3_pretrained_variant,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.types import (
    Sam3InteractivePromptItem,
    Sam3TextPromptGroup,
)


SAM3_MODEL_FAMILY = "sam3"
SAM3_MODEL_SESSION_PAYLOAD_TYPE_ID = "sam3-model-session.v1"

_CONSUMER_CAPABILITY_BY_NODE_TYPE_ID = {
    "custom.sam3.interactive-segment": "interactive",
    "custom.sam3.semantic-segment": "semantic",
    "custom.sam3.video-interactive-segment": "video-interactive",
    "custom.sam3.video-semantic-segment": "video-semantic",
}


@dataclass
class Sam3WorkflowModelSession:
    """一个 Load Checkpoint 节点拥有的 SAM3 模型集合。"""

    interactive: Sam3InteractiveRuntimeSession | None = None
    semantic: Sam3SemanticRuntimeSession | None = None

    def require_interactive(self) -> Sam3InteractiveRuntimeSession:
        """返回 interactive session。"""

        if self.interactive is None:
            raise ServiceConfigurationError("SAM3 session 未加载 interactive 能力")
        return self.interactive

    def require_semantic(self) -> Sam3SemanticRuntimeSession:
        """返回 semantic session。"""

        if self.semantic is None:
            raise ServiceConfigurationError("SAM3 session 未加载 semantic 能力")
        return self.semantic

    def close(self) -> None:
        """按与加载相反的顺序释放全部模型。"""

        if self.semantic is not None:
            self.semantic.close()
            self.semantic = None
        if self.interactive is not None:
            self.interactive.close()
            self.interactive = None


class Sam3WorkflowModelSessionProvider:
    """SAM3 Load Checkpoint 的通用生命周期 provider。"""

    model_family = SAM3_MODEL_FAMILY

    def load(
        self,
        *,
        loader_node: WorkflowGraphNode,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> WorkflowModelSessionLoadResult:
        """解析资产并按实际下游能力构造独立模型。"""

        del runtime_context
        model_asset_id = normalize_model_asset_id(
            loader_node.parameters.get("model_asset_id")
        )
        requested_device = normalize_device(loader_node.parameters.get("device"))
        requested_precision = normalize_precision(
            loader_node.parameters.get("precision")
        )
        variant = resolve_sam3_pretrained_variant(model_asset_id=model_asset_id)
        capabilities = _resolve_capabilities(consumer_node_type_ids)
        needs_interactive = bool(
            {"interactive", "video-interactive"}.intersection(capabilities)
        )
        needs_semantic = bool(
            {"semantic", "video-semantic"}.intersection(capabilities)
        )
        session = Sam3WorkflowModelSession()
        try:
            if needs_interactive:
                session.interactive = Sam3InteractiveRuntimeSession(
                    checkpoint_path=variant.checkpoint_path,
                    model_asset_id=variant.model_asset_id,
                    architecture_id=variant.architecture_id,
                    requested_device_name=requested_device,
                    precision=requested_precision,
                )
            if needs_semantic:
                session.semantic = Sam3SemanticRuntimeSession(
                    checkpoint_path=variant.checkpoint_path,
                    model_asset_id=variant.model_asset_id,
                    architecture_id=variant.architecture_id,
                    requested_device_name=requested_device,
                    precision=requested_precision,
                )
        except Exception:
            session.close()
            raise
        loaded_runtime = session.interactive or session.semantic
        if loaded_runtime is None:
            session.close()
            raise ServiceConfigurationError(
                "SAM3 Load Checkpoint 没有有效的 SAM3 消费节点",
                details={"consumer_node_type_ids": list(consumer_node_type_ids)},
            )
        resolved_precision = _read_runtime_precision(loaded_runtime)
        checkpoint_sha256 = str(
            variant.metadata.get("checkpoint_sha256") or ""
        ).strip() or None
        return WorkflowModelSessionLoadResult(
            session=session,
            model_family=SAM3_MODEL_FAMILY,
            model_asset_id=variant.model_asset_id,
            checkpoint_sha256=checkpoint_sha256,
            resolved_device=loaded_runtime.device_name,
            resolved_precision=resolved_precision,
            capabilities=capabilities,
            metadata={
                "architecture_id": variant.architecture_id,
                "model_version": variant.model_version,
            },
        )

    def warmup(
        self,
        *,
        load_result: WorkflowModelSessionLoadResult,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> object:
        """用固定小图和最小提示完成受控 warmup。"""

        del consumer_node_type_ids, runtime_context
        session = _require_sam3_session(load_result.session)
        image_bytes, image_payload = _build_warmup_image()
        summaries: dict[str, dict[str, object]] = {}
        if session.interactive is not None:
            prediction = session.interactive.predict(
                image_bytes=image_bytes,
                image_payload=image_payload,
                prompt_items=(
                    Sam3InteractivePromptItem(
                        prompt_id="warmup-box",
                        prompt_kind="box",
                        display_name="Warmup Box",
                        bbox_xyxy=(8.0, 8.0, 56.0, 56.0),
                    ),
                ),
            )
            summaries["interactive"] = dict(prediction.summary)
        if session.semantic is not None:
            prediction = session.semantic.predict(
                image_bytes=image_bytes,
                image_payload=image_payload,
                prompt_items=(
                    Sam3TextPromptGroup(
                        prompt_id="warmup-text",
                        display_name="Warmup Object",
                        positive_texts=("object",),
                        negative_texts=(),
                        languages=("en",),
                    ),
                ),
            )
            summaries["semantic"] = dict(prediction.summary)
        return summaries

    def validate(
        self,
        *,
        load_result: WorkflowModelSessionLoadResult,
        warmup_result: object,
        consumer_node_type_ids: tuple[str, ...],
        runtime_context: object,
    ) -> dict[str, object]:
        """验证每个已加载能力都完成了 project-native 推理。"""

        del consumer_node_type_ids, runtime_context
        if not isinstance(warmup_result, dict):
            raise ServiceConfigurationError("SAM3 warmup 没有返回有效摘要")
        expected_modes = {
            "interactive"
            if capability in {"interactive", "video-interactive"}
            else "semantic"
            for capability in load_result.capabilities
        }
        for mode in expected_modes:
            summary = warmup_result.get(mode)
            if not isinstance(summary, dict) or summary.get("project_native") is not True:
                raise ServiceConfigurationError(
                    "SAM3 warmup 输出验证失败",
                    details={"mode": mode},
                )
        return {
            "warmup": "passed",
            "validated_modes": sorted(expected_modes),
        }

    def close(self, session: object) -> None:
        """释放一个 loader 独占的 SAM3 模型。"""

        _require_sam3_session(session).close()


def resolve_sam3_session_lease(
    request: WorkflowNodeExecutionRequest,
    *,
    capability: str,
):
    """从节点输入解析当前 AppRuntime 的 SAM3 lease。"""

    runtime_context = request.runtime_context
    require_manager = getattr(
        runtime_context, "require_workflow_model_session_manager", None
    )
    if not callable(require_manager):
        raise ServiceConfigurationError("SAM3 节点缺少 workflow runtime 上下文")
    manager: WorkflowModelSessionManager = require_manager()
    return manager.resolve_reference(
        request.input_values.get("model"),
        expected_model_family=SAM3_MODEL_FAMILY,
        capability=capability,
    )


def build_sam3_loader_output(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """构造 SAM3 Load Checkpoint 节点的 model 输出。"""

    runtime_context = request.runtime_context
    require_manager = getattr(
        runtime_context, "require_workflow_model_session_manager", None
    )
    if not callable(require_manager):
        raise ServiceConfigurationError(
            "SAM3 Load Checkpoint 缺少 workflow runtime 上下文"
        )
    scope_id = str(
        request.execution_metadata.get(
            WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY, ""
        )
    ).strip()
    if not scope_id:
        raise ServiceConfigurationError("SAM3 Load Checkpoint 缺少 session scope")
    manager: WorkflowModelSessionManager = require_manager()
    return {
        "model": manager.build_reference_payload(
            scope_id=scope_id,
            loader_node_id=request.node_id,
        )
    }


def _resolve_capabilities(
    consumer_node_type_ids: tuple[str, ...],
) -> tuple[str, ...]:
    capabilities: list[str] = []
    unsupported: list[str] = []
    for node_type_id in consumer_node_type_ids:
        capability = _CONSUMER_CAPABILITY_BY_NODE_TYPE_ID.get(node_type_id)
        if capability is None:
            unsupported.append(node_type_id)
        elif capability not in capabilities:
            capabilities.append(capability)
    if unsupported:
        raise ServiceConfigurationError(
            "SAM3 Load Checkpoint 连接了不支持的消费节点",
            details={"consumer_node_type_ids": unsupported},
        )
    return tuple(capabilities)


def _require_sam3_session(session: object) -> Sam3WorkflowModelSession:
    if not isinstance(session, Sam3WorkflowModelSession):
        raise ServiceConfigurationError("SAM3 provider 收到无效 session 对象")
    return session


def _read_runtime_precision(runtime_session: object) -> str:
    dtype_name = str(getattr(runtime_session, "runtime_torch_dtype", ""))
    if dtype_name.endswith("bfloat16"):
        return "bf16"
    if dtype_name.endswith("float16"):
        return "fp16"
    return "fp32"


def _build_warmup_image() -> tuple[bytes, dict[str, object]]:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[16:48, 16:48] = 255
    encoded, buffer = cv2.imencode(".png", image)
    if not encoded:
        raise ServiceConfigurationError("无法构造 SAM3 warmup 图片")
    return buffer.tobytes(), {
        "format_id": "amvision.image-ref.v1",
        "media_type": "image/png",
        "width": 64,
        "height": 64,
        "source": "runtime-warmup",
    }


__all__ = [
    "SAM3_MODEL_FAMILY",
    "SAM3_MODEL_SESSION_PAYLOAD_TYPE_ID",
    "Sam3WorkflowModelSession",
    "Sam3WorkflowModelSessionProvider",
    "build_sam3_loader_output",
    "resolve_sam3_session_lease",
]
