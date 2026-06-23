"""deployment 分类节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.deployment_model import (
    DEFAULT_DIRECT_MODEL_TOP_K,
    run_direct_model_inference,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE


def _deployment_classification_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """通过 PublishedInferenceGateway 调用已发布 classification 推理服务。"""

    inference_result, source_image = run_direct_model_inference(
        request,
        task_type=CLASSIFICATION_TASK_TYPE,
    )
    return {
        "categories": {
            "source_image": dict(source_image),
            "count": len(inference_result.categories),
            "items": [dict(item) for item in inference_result.categories],
            "top_item": dict(inference_result.top_category) if isinstance(inference_result.top_category, dict) else None,
            "image_width": inference_result.image_width,
            "image_height": inference_result.image_height,
            "latency_ms": inference_result.latency_ms,
            "runtime_session_info": dict(inference_result.runtime_session_info),
            "metadata": dict(inference_result.metadata),
        }
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.model.classification",
        display_name="Classification",
        category="model.inference",
        description="调用独立推理 worker 产出标准 classification 结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
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
                name="categories",
                display_name="Categories",
                payload_type_id="categories.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "deployment_instance_id": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "default": DEFAULT_DIRECT_MODEL_TOP_K},
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
            },
            "required": ["deployment_instance_id"],
        },
        capability_tags=("model.inference", "classification"),
        runtime_requirements={"deployment_process": "sync"},
    ),
    handler=_deployment_classification_handler,
)
