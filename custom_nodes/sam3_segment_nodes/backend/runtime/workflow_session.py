"""SAM3 接入通用 Workflow Model Session 生命周期。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import cv2
import numpy as np
import torch

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
from custom_nodes.sam3_segment_nodes.backend.core.checkpoint.loader import (
    load_sam3_checkpoint_branches,
)
from custom_nodes.sam3_segment_nodes.backend.core.models.shared_owner import (
    Sam3SharedModelOwner,
    build_sam3_shared_model_owner,
)
from custom_nodes.sam3_segment_nodes.backend.core.models.multiplex_video import (
    Sam3MultiplexRuntimeSession,
)
from custom_nodes.sam3_segment_nodes.backend.core.state.multiplex import (
    build_sam3_multiplex_state,
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
    multiplex: Sam3MultiplexRuntimeSession | None = None
    shared_owner: Sam3SharedModelOwner | None = None

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

    def require_multiplex(self) -> Sam3MultiplexRuntimeSession:
        """返回 SAM3.1 Multiplex propagation session。"""

        if self.multiplex is None:
            raise ServiceConfigurationError(
                "SAM3 session 未加载 Multiplex propagation 能力"
            )
        return self.multiplex

    def close(self) -> None:
        """按与加载相反的顺序释放全部模型。"""

        if self.multiplex is not None:
            self.multiplex.close()
            self.multiplex = None
        if self.semantic is not None:
            self.semantic.close()
            self.semantic = None
        if self.interactive is not None:
            self.interactive.close()
            self.interactive = None
        if self.shared_owner is not None:
            self.shared_owner.close()
            self.shared_owner = None


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
        checkpoint_sha256 = str(
            variant.metadata.get("checkpoint_sha256") or ""
        ).strip() or None
        capabilities = _resolve_capabilities(consumer_node_type_ids)
        needs_interactive = bool(
            {"interactive", "video-interactive"}.intersection(capabilities)
        )
        needs_semantic = bool(
            {"semantic", "video-semantic"}.intersection(capabilities)
        )
        needs_multiplex = bool(
            {"video-interactive", "video-semantic"}.intersection(
                capabilities
            )
        )
        needs_interactive_model = (
            needs_interactive or "video-semantic" in capabilities
        )
        session = Sam3WorkflowModelSession()
        load_started_at = perf_counter()
        try:
            checkpoint_started_at = perf_counter()
            checkpoint_branches = load_sam3_checkpoint_branches(
                variant.checkpoint_path
            )
            checkpoint_read_ms = round(
                (perf_counter() - checkpoint_started_at) * 1000, 3
            )
            if (
                sum(
                    (
                        int(needs_interactive_model),
                        int(needs_semantic),
                        int(needs_multiplex),
                    )
                )
                >= 2
            ):
                shared_build = build_sam3_shared_model_owner(
                    checkpoint_path=variant.checkpoint_path,
                    requested_device_name=requested_device,
                    precision=requested_precision,
                    checkpoint_branches=checkpoint_branches,
                    include_interactive=needs_interactive_model,
                    include_semantic=needs_semantic,
                    include_multiplex=needs_multiplex,
                )
                session.shared_owner = shared_build.owner
                if shared_build.owner.interactive_model is not None:
                    shared_build.owner.interactive_model.checkpoint_compatibility_summary = (
                        shared_build.compatibility_summary["interactive"]
                    )
                    session.interactive = Sam3InteractiveRuntimeSession(
                        checkpoint_path=variant.checkpoint_path,
                        model_asset_id=variant.model_asset_id,
                        architecture_id=variant.architecture_id,
                        requested_device_name=requested_device,
                        precision=requested_precision,
                        checkpoint_sha256=checkpoint_sha256,
                        prebuilt_model=shared_build.owner.interactive_model,
                        resolved_device_name=shared_build.resolved_device_name,
                        runtime_torch_dtype=shared_build.runtime_torch_dtype,
                        owns_model=False,
                        shared_trunk_cache=shared_build.owner.feature_cache,
                    )
                if shared_build.owner.semantic_model is not None:
                    shared_build.owner.semantic_model.checkpoint_compatibility_summary = (
                        shared_build.compatibility_summary["semantic"]
                    )
                    session.semantic = Sam3SemanticRuntimeSession(
                        checkpoint_path=variant.checkpoint_path,
                        model_asset_id=variant.model_asset_id,
                        architecture_id=variant.architecture_id,
                        requested_device_name=requested_device,
                        precision=requested_precision,
                        checkpoint_sha256=checkpoint_sha256,
                        prebuilt_model=shared_build.owner.semantic_model,
                        resolved_device_name=shared_build.resolved_device_name,
                        runtime_torch_dtype=shared_build.runtime_torch_dtype,
                        owns_model=False,
                        shared_trunk_cache=shared_build.owner.feature_cache,
                    )
                if shared_build.owner.multiplex_model is not None:
                    session.multiplex = Sam3MultiplexRuntimeSession(
                        model=shared_build.owner.multiplex_model,
                        model_asset_id=variant.model_asset_id,
                        architecture_id=variant.architecture_id,
                        checkpoint_sha256=checkpoint_sha256,
                        device_name=shared_build.resolved_device_name,
                        runtime_torch_dtype=shared_build.runtime_torch_dtype,
                        shared_trunk_cache=shared_build.owner.feature_cache,
                        owns_model=False,
                    )
            else:
                if needs_interactive_model:
                    session.interactive = Sam3InteractiveRuntimeSession(
                        checkpoint_path=variant.checkpoint_path,
                        model_asset_id=variant.model_asset_id,
                        architecture_id=variant.architecture_id,
                        requested_device_name=requested_device,
                        precision=requested_precision,
                        checkpoint_branches=checkpoint_branches,
                        checkpoint_sha256=checkpoint_sha256,
                    )
                if needs_semantic:
                    session.semantic = Sam3SemanticRuntimeSession(
                        checkpoint_path=variant.checkpoint_path,
                        model_asset_id=variant.model_asset_id,
                        architecture_id=variant.architecture_id,
                        requested_device_name=requested_device,
                        precision=requested_precision,
                        checkpoint_branches=checkpoint_branches,
                        checkpoint_sha256=checkpoint_sha256,
                    )
            del checkpoint_branches
        except Exception:
            session.close()
            raise
        loaded_runtime = (
            session.interactive or session.semantic or session.multiplex
        )
        if loaded_runtime is None:
            session.close()
            raise ServiceConfigurationError(
                "SAM3 Load Checkpoint 没有有效的 SAM3 消费节点",
                details={"consumer_node_type_ids": list(consumer_node_type_ids)},
            )
        resolved_precision = _read_runtime_precision(loaded_runtime)
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
                "resource_owner": (
                    session.shared_owner.diagnostics()
                    if session.shared_owner is not None
                    else {
                        "owner_kind": "single-capability",
                        "model_instance_count": 1,
                    }
                ),
                "timings_ms": {
                    "checkpoint_read": checkpoint_read_ms,
                    "model_build_and_device_transfer": round(
                        (perf_counter() - load_started_at) * 1000
                        - checkpoint_read_ms,
                        3,
                    ),
                    "load_total": round(
                        (perf_counter() - load_started_at) * 1000,
                        3,
                    ),
                },
            },
        )

    @torch.inference_mode()
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
        warmup_started_at = perf_counter()
        image_bytes, image_payload = _build_warmup_image()
        summaries: dict[str, dict[str, object]] = {}
        capability_timings_ms: dict[str, float] = {}
        if session.interactive is not None:
            capability_started_at = perf_counter()
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
            capability_timings_ms["interactive"] = round(
                (perf_counter() - capability_started_at) * 1000,
                3,
            )
        if session.semantic is not None:
            capability_started_at = perf_counter()
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
            capability_timings_ms["semantic"] = round(
                (perf_counter() - capability_started_at) * 1000,
                3,
            )
        if session.multiplex is not None:
            capability_started_at = perf_counter()
            if session.interactive is None:
                raise ServiceConfigurationError(
                    "SAM3 Multiplex warmup 需要 interactive 首帧初始化能力"
                )
            warmup_prompt = (
                Sam3InteractivePromptItem(
                    prompt_id="warmup-video-box",
                    prompt_kind="box",
                    display_name="Warmup Video Box",
                    bbox_xyxy=(8.0, 8.0, 56.0, 56.0),
                ),
            )
            interactive_context = (
                session.interactive.prepare_frame_context(
                    image_bytes=image_bytes,
                    image_payload=image_payload,
                )
            )
            seed = session.interactive.build_propagation_seed(
                frame_context=interactive_context,
                prompt_items=warmup_prompt,
                refine_iterations=1,
            )
            first_context = session.multiplex.prepare_frame_context(
                image_bytes=image_bytes,
                image_payload=image_payload,
            )
            multiplex_state = build_sam3_multiplex_state(
                object_ids=seed.prompt_ids,
                device=seed.mask_logits.device,
                dtype=first_context.features.pixel_feature.dtype,
                multiplex_count=session.multiplex.model.multiplex_count,
            )
            object_pointers = (
                session.multiplex.model.project_interactive_object_tokens(
                    seed.object_tokens.to(
                        dtype=first_context.features.pixel_feature.dtype
                    )
                )
            )
            object_score_logits = seed.mask_logits.new_full(
                (len(seed.prompt_ids), 1),
                10.0,
            )
            first_memory = session.multiplex.model.encode_memory(
                frame_index=0,
                frame_features=first_context.features,
                multiplex_state=multiplex_state,
                mask_logits=seed.mask_logits,
                object_score_logits=object_score_logits,
                object_pointers=multiplex_state.mux(object_pointers),
                conditioning=True,
            )
            second_context = session.multiplex.prepare_frame_context(
                image_bytes=image_bytes,
                image_payload=image_payload,
            )
            propagation = session.multiplex.model.propagate(
                frame_index=1,
                frame_features=second_context.features,
                multiplex_state=multiplex_state,
                memory_entries=(first_memory,),
                total_frame_count=2,
            )
            if (
                propagation.mask_logits.shape[0] != len(seed.prompt_ids)
                or not bool(torch.isfinite(propagation.mask_logits).all())
            ):
                raise ServiceConfigurationError(
                    "SAM3 Multiplex warmup 输出无效"
                )
            summaries["multiplex"] = {
                **session.multiplex.diagnostics(),
                "project_native": True,
                "propagated_object_count": len(seed.prompt_ids),
                "second_frame_validated": True,
            }
            capability_timings_ms["multiplex"] = round(
                (perf_counter() - capability_started_at) * 1000,
                3,
            )
        summaries["_warmup_timings_ms"] = {
            **capability_timings_ms,
            "total": round((perf_counter() - warmup_started_at) * 1000, 3),
        }
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
        expected_modes: set[str] = set()
        for capability in load_result.capabilities:
            if capability in {"interactive", "video-interactive"}:
                expected_modes.add("interactive")
            if capability in {"semantic", "video-semantic"}:
                expected_modes.add("semantic")
            if capability in {"video-interactive", "video-semantic"}:
                expected_modes.add("multiplex")
        for mode in expected_modes:
            summary = warmup_result.get(mode)
            if not isinstance(summary, dict) or summary.get("project_native") is not True:
                raise ServiceConfigurationError(
                    "SAM3 warmup 输出验证失败",
                    details={"mode": mode},
                )
        session = _require_sam3_session(load_result.session)
        warmup_timings = warmup_result.get("_warmup_timings_ms")
        runtime_instances = [
            capability
            for capability, runtime_session in (
                ("interactive", session.interactive),
                ("semantic", session.semantic),
                ("multiplex-propagation", session.multiplex),
            )
            if runtime_session is not None
        ]
        return {
            "warmup": "passed",
            "validated_modes": sorted(expected_modes),
            "runtime_instance_count": (
                1 if session.shared_owner is not None else len(runtime_instances)
            ),
            "runtime_instances": runtime_instances,
            "resource_owner": (
                session.shared_owner.diagnostics()
                if session.shared_owner is not None
                else {
                    "owner_kind": "single-capability",
                    "model_instance_count": len(runtime_instances),
                }
            ),
            "warmup_timings_ms": (
                dict(warmup_timings)
                if isinstance(warmup_timings, dict)
                else {}
            ),
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
