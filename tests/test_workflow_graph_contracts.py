"""workflow graph 规则测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import (
    FLOW_APPLICATION_RUNTIME_PYTHON_JSON,
    NODE_IMPLEMENTATION_CORE,
    NODE_IMPLEMENTATION_CUSTOM,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NODE_RUNTIME_WORKER_TASK,
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphGroup,
    WorkflowGraphGroupRect,
    WorkflowGraphNode,
    WorkflowGraphNote,
    WorkflowGraphNoteRect,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
    synchronize_flow_application_bindings,
    validate_flow_application_bindings,
    validate_node_definition_catalog,
    validate_workflow_graph_template,
)
from backend.service.application.workflows.execution.topology import (
    build_node_execution_scope_template,
)


def _build_payload_contracts() -> tuple[WorkflowPayloadContract, ...]:
    """构造测试使用的最小 payload 规则 集合。"""

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
            category="core.io.input",
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
            node_type_id="core.model.detection",
            display_name="Detection",
            category="core.model.inference",
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
            capability_tags=("model.inference", "detection"),
            runtime_requirements={"worker_pool": "detection-inference"},
        ),
        NodeDefinition(
            node_type_id="custom.opencv.draw-detections",
            display_name="Draw Detections",
            category="opencv.output.render",
            description="通过 OpenCV 把 detection 结果叠加到图片上，生成结构化 HTTP 回包。",
            implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
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
            node_pack_id="opencv.nodes",
            node_pack_version="0.1.3",
        ),
    )


def test_node_definition_rejects_slash_category_paths() -> None:
    """验证公开 category 不再接受斜杠多级路径。"""

    with pytest.raises(ValueError, match="不能包含 /"):
        NodeDefinition(
            node_type_id="core.test.invalid-category",
            display_name="Invalid Category",
            category="core/logic/branch",
            implementation_kind=NODE_IMPLEMENTATION_CORE,
            runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        )


def _build_parameter_input_node_definition(
    *,
    input_port: NodePortDefinition | None = None,
    bindings: tuple[NodeParameterInputBinding, ...] | None = None,
    parameter_schema: dict[str, object] | None = None,
) -> NodeDefinition:
    """构造参数输入绑定契约测试使用的最小节点定义。"""

    return NodeDefinition(
        node_type_id="core.test.parameter-input",
        display_name="Parameter Input",
        category="test",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            input_port
            or NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_schema=parameter_schema
        or {
            "type": "object",
            "properties": {"threshold": {"type": "number", "default": 0.5}},
        },
        parameter_input_bindings=bindings
        if bindings is not None
        else (
            NodeParameterInputBinding(
                parameter_name="threshold",
                input_port_name="threshold",
            ),
        ),
    )


def test_node_definition_parameter_input_binding_round_trips_as_v1() -> None:
    """验证参数输入绑定是当前 NodeDefinition v1 的向后兼容字段。"""

    definition = _build_parameter_input_node_definition()
    restored = NodeDefinition.model_validate_json(definition.model_dump_json())
    legacy_payload = definition.model_dump(mode="json")
    legacy_payload.pop("parameter_input_bindings")
    legacy_definition = NodeDefinition.model_validate(legacy_payload)

    assert definition.format_id == "amvision.node-definition.v1"
    assert restored.parameter_input_bindings == definition.parameter_input_bindings
    assert legacy_definition.parameter_input_bindings == ()


@pytest.mark.parametrize(
    ("input_port", "bindings", "parameter_schema", "expected_message"),
    (
        (
            None,
            (
                NodeParameterInputBinding(
                    parameter_name="missing",
                    input_port_name="threshold",
                ),
            ),
            None,
            "不存在的参数",
        ),
        (
            None,
            (
                NodeParameterInputBinding(
                    parameter_name="threshold",
                    input_port_name="missing",
                ),
            ),
            None,
            "不存在的输入端口",
        ),
        (
            NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                required=True,
            ),
            None,
            None,
            "必须是可选端口",
        ),
        (
            NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                required=False,
                multiple=True,
            ),
            None,
            None,
            "不允许 multiple",
        ),
        (
            NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="text.v1",
                required=False,
            ),
            None,
            None,
            "必须使用 value.v1",
        ),
        (
            None,
            None,
            {"type": "object"},
            "parameter_schema.properties 必须是对象",
        ),
    ),
)
def test_node_definition_rejects_invalid_parameter_input_bindings(
    input_port: NodePortDefinition | None,
    bindings: tuple[NodeParameterInputBinding, ...] | None,
    parameter_schema: dict[str, object] | None,
    expected_message: str,
) -> None:
    """验证动态参数绑定不会接受不明确或非 value.v1 的端口。"""

    with pytest.raises(ValueError, match=expected_message):
        _build_parameter_input_node_definition(
            input_port=input_port,
            bindings=bindings,
            parameter_schema=parameter_schema,
        )


def test_node_definition_rejects_duplicate_parameter_input_bindings() -> None:
    """验证一个参数不能由多个端口静默覆盖。"""

    with pytest.raises(ValueError, match="动态参数绑定参数 存在重复名称"):
        _build_parameter_input_node_definition(
            input_port=NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                required=False,
            ),
            bindings=(
                NodeParameterInputBinding(
                    parameter_name="threshold",
                    input_port_name="threshold",
                ),
                NodeParameterInputBinding(
                    parameter_name="threshold",
                    input_port_name="threshold_backup",
                ),
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
                node_type_id="core.model.detection",
                parameters={"score_threshold": 0.3},
                ui_state={"position": {"x": 280, "y": 60}},
            ),
            WorkflowGraphNode(
                node_id="draw_response",
                node_type_id="custom.opencv.draw-detections",
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
                input_id="request_image_base64",
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
    """验证 payload 规则、节点目录、图模板和流程应用可以稳定保存与加载。"""

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
                template_port_id="request_image_base64",
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
    assert restored_definition.node_pack_id == "opencv.nodes"
    assert restored_definition.runtime_requirements["python_packages"] == ["opencv-python", "numpy"]
    assert restored_template.nodes[1].parameters["score_threshold"] == 0.3
    assert restored_application.bindings[0].binding_kind == "api-request"


def test_workflow_graph_notes_roundtrip_and_legacy_defaults() -> None:
    """验证说明节点随 v1 Template 往返，旧文档缺少新字段时使用空集合。"""

    source_payload = _build_graph_template().model_dump(mode="json")
    source_payload["notes"] = [
        WorkflowGraphNote(
            note_id="note-input-guide",
            title="输入说明",
            content="## 输入\n\n- request_image_ref：检测图片",
            rect=WorkflowGraphNoteRect(x=80, y=20, width=420, height=260),
            tone="info",
        ).model_dump(mode="json")
    ]
    source_payload["groups"] = [
        WorkflowGraphGroup(
            group_id="group-input",
            name="输入",
            rect=WorkflowGraphGroupRect(x=0, y=0, width=700, height=480),
            member_node_ids=("input_image",),
            member_note_ids=("note-input-guide",),
        ).model_dump(mode="json")
    ]

    template = WorkflowGraphTemplate.model_validate(source_payload)
    restored = WorkflowGraphTemplate.model_validate_json(template.model_dump_json())

    assert restored.format_id == "amvision.workflow-graph-template.v1"
    assert restored.notes[0].note_id == "note-input-guide"
    assert restored.notes[0].content_format == "markdown"
    assert restored.groups[0].member_note_ids == ("note-input-guide",)

    legacy_payload = template.model_dump(mode="json")
    legacy_payload.pop("notes")
    for group in legacy_payload["groups"]:
        group.pop("member_note_ids")
    legacy_template = WorkflowGraphTemplate.model_validate(legacy_payload)

    assert legacy_template.notes == ()
    assert legacy_template.groups[0].member_note_ids == ()


def test_workflow_graph_template_rejects_invalid_note_references() -> None:
    """验证说明节点 id 和节点组引用必须明确且存在。"""

    payload = _build_graph_template().model_dump(mode="json")
    note = WorkflowGraphNote(
        note_id="note-1",
        title="说明",
        rect=WorkflowGraphNoteRect(x=0, y=0, width=320, height=180),
    ).model_dump(mode="json")
    payload["notes"] = [note, {**note, "title": "重复说明"}]
    with pytest.raises(ValueError, match="图模板说明节点 存在重复名称"):
        WorkflowGraphTemplate.model_validate(payload)

    payload["notes"] = [note]
    payload["groups"] = [
        WorkflowGraphGroup(
            group_id="group-1",
            name="说明组",
            rect=WorkflowGraphGroupRect(x=0, y=0, width=500, height=300),
            member_note_ids=("missing-note",),
        ).model_dump(mode="json")
    ]
    with pytest.raises(ValueError, match="不存在的 member_note_id"):
        WorkflowGraphTemplate.model_validate(payload)


def test_node_execution_scope_excludes_editor_notes() -> None:
    """验证节点级执行域不会携带说明节点和说明分组归属。"""

    payload = _build_graph_template().model_dump(mode="json")
    payload["notes"] = [
        WorkflowGraphNote(
            note_id="note-1",
            title="仅编辑器可见",
            rect=WorkflowGraphNoteRect(x=0, y=0, width=320, height=180),
        ).model_dump(mode="json")
    ]
    payload["groups"] = [
        WorkflowGraphGroup(
            group_id="group-1",
            name="执行组",
            rect=WorkflowGraphGroupRect(x=0, y=0, width=900, height=500),
            member_node_ids=("input_image", "detect"),
            member_note_ids=("note-1",),
        ).model_dump(mode="json")
    ]
    template = WorkflowGraphTemplate.model_validate(payload)

    scoped = build_node_execution_scope_template(
        template=template,
        target_node_id="detect",
    )

    assert scoped.notes == ()
    assert scoped.groups[0].member_node_ids == ("input_image", "detect")
    assert scoped.groups[0].member_note_ids == ()

def test_workflow_graph_note_rejects_invalid_size_limits() -> None:
    """验证说明节点正文、矩形、数量和 Template 总正文量都有明确上限。"""

    with pytest.raises(ValueError, match="content 不能超过"):
        WorkflowGraphNote(
            note_id="note-large",
            title="过大正文",
            content="测" * 21846,
            rect=WorkflowGraphNoteRect(x=0, y=0, width=320, height=180),
        )

    with pytest.raises(ValueError, match="rect.width"):
        WorkflowGraphNoteRect(x=0, y=0, width=219, height=180)

    payload = _build_graph_template().model_dump(mode="json")
    payload["notes"] = [
        {
            "note_id": f"note-{index}",
            "title": f"说明 {index}",
            "content": "",
            "content_format": "markdown",
            "rect": {"x": 0, "y": 0, "width": 320, "height": 180},
            "tone": "neutral",
            "collapsed": False,
            "locked": False,
            "metadata": {},
        }
        for index in range(129)
    ]
    with pytest.raises(ValueError, match="不能超过 128 个"):
        WorkflowGraphTemplate.model_validate(payload)

    payload["notes"] = [
        {
            "note_id": f"note-{index}",
            "title": f"说明 {index}",
            "content": "x" * (64 * 1024),
            "content_format": "markdown",
            "rect": {"x": 0, "y": 0, "width": 320, "height": 180},
            "tone": "neutral",
            "collapsed": False,
            "locked": False,
            "metadata": {},
        }
        for index in range(17)
    ]
    with pytest.raises(ValueError, match="正文总量不能超过"):
        WorkflowGraphTemplate.model_validate(payload)


def test_flow_application_bindings_sync_with_current_template_ports() -> None:
    """验证模板公开端口变化后应用绑定会被同步到最新合同。"""

    graph_template = _build_graph_template()
    stale_application = FlowApplication(
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
                binding_id="request_image_base64",
                direction="input",
                template_port_id="request_image_base64",
                binding_kind="api-request",
                required=True,
            ),
            FlowApplicationBinding(
                binding_id="legacy_response",
                direction="output",
                template_port_id="legacy_response",
                binding_kind="http-response",
            ),
        ),
    )

    with pytest.raises(ValueError, match="不存在的模板输出"):
        validate_flow_application_bindings(template=graph_template, application=stale_application)

    synchronized_application = synchronize_flow_application_bindings(
        template=graph_template,
        application=stale_application,
    )

    validate_flow_application_bindings(template=graph_template, application=synchronized_application)
    assert [binding.binding_id for binding in synchronized_application.bindings] == [
        "request_image_base64",
        "inspection_response",
    ]
    output_binding = synchronized_application.bindings[1]
    assert output_binding.template_port_id == "inspection_response"
    assert output_binding.binding_kind == "http-response"
    assert output_binding.config["payload_type_id"] == "http-response.v1"


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

