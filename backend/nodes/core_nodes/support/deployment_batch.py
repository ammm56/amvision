"""五类通用 deployment Batch 节点的共享规格构造。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.deployment_model import (
    DEFAULT_DIRECT_MODEL_KEYPOINT_CONFIDENCE_THRESHOLD,
    DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
    DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
    DEFAULT_DIRECT_MODEL_TOP_K,
    run_direct_model_batch_inference,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.version import BACKEND_VERSION


def build_deployment_batch_node_spec(
    *,
    node_type_id: str,
    display_name: str,
    task_type: str,
    output_name: str,
    output_display_name: str,
    output_payload_type_id: str,
    format_id: str,
) -> CoreNodeSpec:
    """构造一个使用同部署、同参数、有序输入的模型 Batch 节点。"""

    def handle_batch(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        """执行一次跨进程 Batch 调用。"""

        return {
            output_name: run_direct_model_batch_inference(
                request,
                task_type=task_type,
                format_id=format_id,
                result_payload_type_id=_result_payload_type_id(task_type),
            )
        }

    return CoreNodeSpec(
        node_definition=NodeDefinition(
            version=BACKEND_VERSION,
            node_type_id=node_type_id,
            display_name=display_name,
            category="core.model.inference",
            description=(
                "占用一个同步 deployment instance，按输入顺序完成整批图片推理；"
                "不排队、不拆批、不重试。"
            ),
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_WORKER_TASK,
            concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
            input_ports=(
                NodePortDefinition(
                    name="images",
                    display_name="Images",
                    payload_type_id="image-refs.v1",
                ),
                NodePortDefinition(
                    name="dependency",
                    display_name="Dependency",
                    payload_type_id="response-body.v1",
                    required=False,
                ),
                NodePortDefinition(
                    name="request",
                    display_name="Request",
                    payload_type_id="value.v1",
                    required=False,
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name=output_name,
                    display_name=output_display_name,
                    payload_type_id=output_payload_type_id,
                ),
            ),
            parameter_schema={
                "type": "object",
                "properties": _build_parameter_properties(task_type),
                "required": ["deployment_instance_id"],
            },
            capability_tags=(
                "model.inference",
                "model.inference.batch",
                task_type,
            ),
            runtime_requirements={
                "deployment_process": "sync",
                "execution_mode": "sequential-reserved-instance",
            },
        ),
        handler=handle_batch,
    )


def _build_parameter_properties(task_type: str) -> dict[str, object]:
    """构造与对应单图节点一致的任务参数，排除 Batch 不支持的预览图参数。"""

    properties: dict[str, object] = {
        "deployment_instance_id": {"type": "string", "minLength": 1},
        "auto_start_process": {"type": "boolean", "default": True},
        "extra_options": {"type": "object", "default": {}},
    }
    if task_type == CLASSIFICATION_TASK_TYPE:
        properties["top_k"] = {
            "type": "integer",
            "minimum": 1,
            "default": DEFAULT_DIRECT_MODEL_TOP_K,
        }
        return properties
    properties["score_threshold"] = {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "default": DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
    }
    if task_type == SEGMENTATION_TASK_TYPE:
        properties["mask_threshold"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
        }
    elif task_type == POSE_TASK_TYPE:
        properties["keypoint_confidence_threshold"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": DEFAULT_DIRECT_MODEL_KEYPOINT_CONFIDENCE_THRESHOLD,
        }
    elif task_type not in {DETECTION_TASK_TYPE, OBB_TASK_TYPE}:
        raise ValueError(f"不支持的 deployment Batch task_type: {task_type}")
    return properties


def _result_payload_type_id(task_type: str) -> str:
    """返回 Batch item.result 对应的现有单项 payload type。"""

    mapping = {
        DETECTION_TASK_TYPE: "detections.v1",
        CLASSIFICATION_TASK_TYPE: "categories.v1",
        SEGMENTATION_TASK_TYPE: "segments.v1",
        POSE_TASK_TYPE: "poses.v1",
        OBB_TASK_TYPE: "obbs.v1",
    }
    try:
        return mapping[task_type]
    except KeyError as error:
        raise ValueError(
            f"不支持的 deployment Batch task_type: {task_type}"
        ) from error
