"""workflow 可选输入与双输入图节点测试。"""

from __future__ import annotations

import base64
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FLOW_BINDING_DIRECTION_INPUT,
    FLOW_BINDING_DIRECTION_OUTPUT,
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.snapshot_execution import _build_template_input_values
from tests.api_test_support import build_valid_test_png_bytes


def test_build_binding_inputs_allows_missing_optional_bindings() -> None:
    """验证 application 输入绑定被标记为可选后，可以只提供其中一个输入。"""

    request_image_payload = {"image_base64": "dGVzdA==", "media_type": "image/png"}
    application = FlowApplication(
        application_id="dual-input-application",
        display_name="Dual Input Application",
        template_ref=FlowTemplateReference(
            template_id="dual-input-template",
            template_version="1.0.0",
            source_kind="embedded",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image_base64",
                direction=FLOW_BINDING_DIRECTION_INPUT,
                template_port_id="request_image_base64",
                binding_kind="api-request",
                required=False,
            ),
            FlowApplicationBinding(
                binding_id="request_image_ref",
                direction=FLOW_BINDING_DIRECTION_INPUT,
                template_port_id="request_image_ref",
                binding_kind="trigger-source-input",
                required=False,
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction=FLOW_BINDING_DIRECTION_OUTPUT,
                template_port_id="http_response",
                binding_kind="http-response",
            ),
        ),
        runtime_mode="python-json-workflow",
    )

    resolved_inputs = _build_template_input_values(
        application=application,
        input_bindings={"request_image_base64": request_image_payload},
    )

    assert resolved_inputs == {"request_image_base64": request_image_payload}


def test_graph_executor_allows_dual_image_inputs_to_arrive_separately(tmp_path: Path) -> None:
    """验证双输入图片图可以分别接收 HTTP base64 和 image-ref 两条通道。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    image_registry = ExecutionImageRegistry()
    source_bytes = build_valid_test_png_bytes()
    template = _build_dual_input_image_template()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())

    http_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "image_base64": base64.b64encode(source_bytes).decode("ascii"),
                "media_type": "image/png",
            }
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/png",
        width=8,
        height=8,
        created_by_node_id="fixture",
    )
    image_ref_result = executor.execute(
        template=template,
        input_values={
            "request_image_ref": build_memory_image_payload(
                image_handle=registered_image.image_handle,
                media_type="image/png",
                width=registered_image.width,
                height=registered_image.height,
            )
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    http_image_payload = http_result.outputs["image"]
    image_ref_payload = image_ref_result.outputs["image"]

    assert http_image_payload["transport_kind"] == "memory"
    assert image_ref_payload["transport_kind"] == "memory"
    assert image_registry.read_bytes(str(http_image_payload["image_handle"])) == source_bytes
    assert image_registry.read_bytes(str(image_ref_payload["image_handle"])) == source_bytes


def _build_dual_input_image_template() -> WorkflowGraphTemplate:
    """构造一个最小双输入图片模板。

    返回：
    - WorkflowGraphTemplate：支持 image-base64 与 image-ref 分通道进入的最小模板。
    """

    return WorkflowGraphTemplate(
        template_id="dual-input-image-template",
        template_version="1.0.0",
        display_name="Dual Input Image Template",
        nodes=(
            WorkflowGraphNode(
                node_id="encode_request_image_ref",
                node_type_id="core.io.image-base64-encode",
            ),
            WorkflowGraphNode(
                node_id="resolve_request_image",
                node_type_id="core.logic.image-base64-coalesce",
            ),
            WorkflowGraphNode(
                node_id="decode_request_image",
                node_type_id="core.io.image-base64-decode",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-encode-request-image-ref",
                source_node_id="encode_request_image_ref",
                source_port="payload",
                target_node_id="resolve_request_image",
                target_port="fallback",
            ),
            WorkflowGraphEdge(
                edge_id="edge-resolve-request-image",
                source_node_id="resolve_request_image",
                source_port="payload",
                target_node_id="decode_request_image",
                target_port="payload",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image Base64",
                payload_type_id="image-base64.v1",
                target_node_id="resolve_request_image",
                target_port="primary",
                required=False,
            ),
            WorkflowGraphInput(
                input_id="request_image_ref",
                display_name="Request Image Ref",
                payload_type_id="image-ref.v1",
                target_node_id="encode_request_image_ref",
                target_port="image",
                required=False,
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                source_node_id="decode_request_image",
                source_port="image",
            ),
        ),
    )