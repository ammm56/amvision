"""workflow graph 合同测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import (
    FLOW_APPLICATION_RUNTIME_PYTHON_JSON,
    NODE_IMPLEMENTATION_CORE,
    NODE_IMPLEMENTATION_PLUGIN,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NODE_RUNTIME_WORKER_TASK,
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    NodeDefinition,
    NodePortDefinition,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
    validate_flow_application_bindings,
    validate_node_definition_catalog,
    validate_workflow_graph_template,
)


def _build_payload_contracts() -> tuple[WorkflowPayloadContract, ...]:
    """构造测试使用的最小 payload contract 集合。"""

    return (
        WorkflowPayloadContract(
            payload_type_id="image-ref.v1",
            display_name="Image Reference",
            transport_kind="artifact-ref",
            json_schema={
                "type": "object",
                "properties": {
                    "object_key": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["object_key"],
            },
            artifact_kinds=("image",),
        ),
        WorkflowPayloadContract(
            payload_type_id="detections.v1",
            display_name="Detection Result",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "bbox_xyxy": {"type": "array"},
                                "score": {"type": "number"},
                                "class_name": {"type": "string"},
                            },
                            "required": ["bbox_xyxy", "score"],
                        },
                    }
                },
                "required": ["items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="http-response.v1",
            display_name="HTTP Response",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "object"},
                },
                "required": ["status_code", "body"],
            },
        ),
    )


def _build_node_definitions() -> tuple[NodeDefinition, ...]:
    """构造测试使用的最小节点目录。"""

    return (
        NodeDefinition(
            node_type_id="core.io.template-input.image",
            display_name="Template Image Input",
            category="io.input",
            description="接收流程应用绑定进来的图片引用，并输出给后续节点。",
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
            input_ports=(
                NodePortDefinition(
                    name="payload",
                    display_name="Payload",
                    payload_type_id="image-ref.v1",
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name="image",
                    display_name="Image",
                    payload_type_id="image-ref.v1",
                ),
            ),
            parameter_schema={"type": "object", "properties": {}},
        ),
        NodeDefinition(
            node_type_id="core.model.yolox-detection",
            display_name="YOLOX Detection",
            category="model.inference",
            description="调用独立推理 worker 产出标准 detection 结果。",
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_WORKER_TASK,
            input_ports=(
                NodePortDefinition(
                    name="image",
                    display_name="Image",
                    payload_type_id="image-ref.v1",
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name="detections",
                    display_name="Detections",
                    payload_type_id="detections.v1",
                ),
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "score_threshold": {"type": "number", "minimum": 0, "maximum": 1}
                },
            },
            capability_tags=("model.inference", "yolox.detection"),
            runtime_requirements={"worker_pool": "yolox-inference"},
        ),
        NodeDefinition(
            node_type_id="plugin.opencv.draw-detections",
            display_name="Draw Detections",
            category="opencv.render",
            description="通过 OpenCV 把 detection 结果叠加到图片上，生成结构化 HTTP 回包。",
            implementation_kind=NODE_IMPLEMENTATION_PLUGIN,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
            input_ports=(
                NodePortDefinition(
                    name="image",
                    display_name="Image",
                    payload_type_id="image-ref.v1",
                ),
                NodePortDefinition(
                    name="detections",
                    display_name="Detections",
                    payload_type_id="detections.v1",
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name="response",
                    display_name="Response",
                    payload_type_id="http-response.v1",
                ),
            ),
            parameter_schema={
                "type": "object",
                "properties": {
                    "line_thickness": {"type": "integer", "minimum": 1},
                    "render_preview": {"type": "boolean"},
                },
            },
            capability_tags=("opencv.draw", "vision.render", "result.aggregate"),
            runtime_requirements={"python_packages": ["opencv-python", "numpy"]},
            plugin_id="opencv.basic-nodes",
            plugin_version="0.1.0",
        ),
    )


def _build_graph_template() -> WorkflowGraphTemplate:
    """构造测试使用的最小图模板。"""

    return WorkflowGraphTemplate(
        template_id="inspection-demo",
        template_version="1.0.0",
        display_name="Inspection Demo",
        description="演示模板负责图结构，应用负责输入输出端点绑定。",
        nodes=(
            WorkflowGraphNode(
                node_id="input_image",
                node_type_id="core.io.template-input.image",
                ui_state={"position": {"x": 20, "y": 60}},
            ),
            WorkflowGraphNode(
                node_id="detect",
                node_type_id="core.model.yolox-detection",
                parameters={"score_threshold": 0.3},
                ui_state={"position": {"x": 280, "y": 60}},
            ),
            WorkflowGraphNode(
                node_id="draw_response",
                node_type_id="plugin.opencv.draw-detections",
                parameters={"line_thickness": 2, "render_preview": True},
                ui_state={"position": {"x": 560, "y": 60}},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-image",
                source_node_id="input_image",
                source_port="image",
                target_node_id="detect",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-preview",
                source_node_id="input_image",
                source_port="image",
                target_node_id="draw_response",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-detect-draw",
                source_node_id="detect",
                source_port="detections",
                target_node_id="draw_response",
                target_port="detections",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input_image",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="draw_response",
                source_port="response",
            ),
        ),
    )


def test_workflow_contracts_roundtrip_and_binding_validation() -> None:
    """验证 payload contract、节点目录、图模板和流程应用可以稳定保存与加载。"""

    payload_contracts = _build_payload_contracts()
    node_definitions = _build_node_definitions()
    graph_template = _build_graph_template()
    flow_application = FlowApplication(
        application_id="inspection-api-app",
        display_name="Inspection API App",
        template_ref=FlowTemplateReference(
            template_id="inspection-demo",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="workflows/inspection-demo.template.json",
        ),
        runtime_mode=FLOW_APPLICATION_RUNTIME_PYTHON_JSON,
        bindings=(
            FlowApplicationBinding(
                binding_id="api-entry",
                direction="input",
                template_port_id="request_image",
                binding_kind="api-request",
                config={"route": "/api/v1/inspect", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="api-return",
                direction="output",
                template_port_id="inspection_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )

    validate_node_definition_catalog(
        node_definitions=node_definitions,
        payload_contracts=payload_contracts,
    )
    validate_workflow_graph_template(
        template=graph_template,
        node_definitions=node_definitions,
    )
    validate_flow_application_bindings(
        template=graph_template,
        application=flow_application,
    )

    restored_contract = WorkflowPayloadContract.model_validate_json(
        payload_contracts[0].model_dump_json()
    )
    restored_definition = NodeDefinition.model_validate_json(node_definitions[2].model_dump_json())
    restored_template = WorkflowGraphTemplate.model_validate_json(graph_template.model_dump_json())
    restored_application = FlowApplication.model_validate_json(flow_application.model_dump_json())

    assert restored_contract.payload_type_id == "image-ref.v1"
    assert restored_definition.plugin_id == "opencv.basic-nodes"
    assert restored_definition.runtime_requirements["python_packages"] == ["opencv-python", "numpy"]
    assert restored_template.nodes[1].parameters["score_threshold"] == 0.3
    assert restored_application.bindings[0].binding_kind == "api-request"


def test_workflow_graph_template_rejects_cycles() -> None:
    """验证图模板校验会拒绝存在环路的节点图。"""

    node_definitions = (
        NodeDefinition(
            node_type_id="core.pass-through",
            display_name="Pass Through",
            category="utility",
            description="把同一种 payload 透传到下游。",
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
            input_ports=(
                NodePortDefinition(
                    name="payload",
                    display_name="Payload",
                    payload_type_id="image-ref.v1",
                ),
            ),
            output_ports=(
                NodePortDefinition(
                    name="payload",
                    display_name="Payload",
                    payload_type_id="image-ref.v1",
                ),
            ),
            parameter_schema={"type": "object", "properties": {}},
        ),
    )
    cyclic_template = WorkflowGraphTemplate(
        template_id="cyclic-demo",
        template_version="1.0.0",
        display_name="Cyclic Demo",
        nodes=(
            WorkflowGraphNode(node_id="node_a", node_type_id="core.pass-through"),
            WorkflowGraphNode(node_id="node_b", node_type_id="core.pass-through"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-a-b",
                source_node_id="node_a",
                source_port="payload",
                target_node_id="node_b",
                target_port="payload",
            ),
            WorkflowGraphEdge(
                edge_id="edge-b-a",
                source_node_id="node_b",
                source_port="payload",
                target_node_id="node_a",
                target_port="payload",
            ),
        ),
    )

    with pytest.raises(ValueError, match="DAG"):
        validate_workflow_graph_template(
            template=cyclic_template,
            node_definitions=node_definitions,
        )