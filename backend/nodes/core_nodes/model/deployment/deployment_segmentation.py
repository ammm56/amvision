"""deployment 分割节点。"""

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
    DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
    DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
    run_direct_model_inference,
)
from backend.nodes.core_nodes.support.deployment_result_payloads import (
    build_deployment_result_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.version import BACKEND_VERSION


def _deployment_segmentation_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """通过 PublishedInferenceGateway 调用已发布 segmentation 推理服务。"""

    inference_result, source_image = run_direct_model_inference(
        request,
        task_type=SEGMENTATION_TASK_TYPE,
    )
    return {
        "segments": build_deployment_result_payload(
            task_type=SEGMENTATION_TASK_TYPE,
            inference_result=inference_result,
            source_image=source_image,
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        version=BACKEND_VERSION,
        node_type_id="core.model.segmentation",
        display_name="Segmentation",
        category="core.model.inference",
        description="调用独立推理 worker 产出标准 segmentation 结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
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
                name="segments",
                display_name="Segments",
                payload_type_id="segments.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "deployment_instance_id": {"type": "string"},
                "score_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": DEFAULT_DIRECT_MODEL_SCORE_THRESHOLD,
                },
                "mask_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": DEFAULT_DIRECT_MODEL_MASK_THRESHOLD,
                },
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
            },
            "required": ["deployment_instance_id"],
        },
        capability_tags=("model.inference", "segmentation"),
        runtime_requirements={"deployment_process": "sync"},
    ),
    handler=_deployment_segmentation_handler,
)
