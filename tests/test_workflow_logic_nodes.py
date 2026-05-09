"""workflow 逻辑节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.application.workflows.runtime_service import WorkflowPreviewRunCreateRequest
from tests.test_workflow_runtime_sanitization import _build_runtime_service


def test_preview_run_logic_nodes_extract_compare_and_select_values(tmp_path: Path) -> None:
    """验证字段提取、比较和 if else 选择节点可以组成最小逻辑链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    task_service = SqlAlchemyTaskService(service.session_factory)
    task_record = task_service.create_task(
        CreateTaskRequest(
            project_id="project-1",
            task_kind="logic-task",
            display_name="Logic Task",
            created_by="tester",
            metadata={"source": "logic-test"},
        )
    )
    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id=task_record.task_id,
            event_type="progress",
            message="task progressed",
            payload={
                "state": "running",
                "progress": {"percent": 75},
            },
        )
    )
    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id=task_record.task_id,
            event_type="result",
            message="task completed",
            payload={
                "state": "succeeded",
                "result": {
                    "model_version_id": "model-version-logic-1",
                    "model_build_id": "model-build-logic-1",
                },
            },
        )
    )

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_logic_application(),
            template=_build_logic_template(task_id=task_record.task_id),
            input_bindings={},
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["selected_value"]["value"] == "model-build-logic-1"
    assert preview_run.outputs["progress_gt"]["value"] is True
    assert preview_run.outputs["progress_lt"]["value"] is True


def _build_logic_template(*, task_id: str) -> WorkflowGraphTemplate:
    """构造逻辑节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="logic-nodes-template",
        template_version="1.0.0",
        display_name="Logic Nodes Template",
        nodes=(
            WorkflowGraphNode(
                node_id="task_get",
                node_type_id="core.service.task.get",
                parameters={"task_id": task_id, "include_events": False},
            ),
            WorkflowGraphNode(
                node_id="extract_state",
                node_type_id="core.logic.field-extract",
                parameters={"path": "state"},
            ),
            WorkflowGraphNode(
                node_id="extract_build",
                node_type_id="core.logic.field-extract",
                parameters={"path": "result.model_build_id"},
            ),
            WorkflowGraphNode(
                node_id="extract_version",
                node_type_id="core.logic.field-extract",
                parameters={"path": "result.model_version_id"},
            ),
            WorkflowGraphNode(
                node_id="extract_percent",
                node_type_id="core.logic.field-extract",
                parameters={"path": "progress.percent"},
            ),
            WorkflowGraphNode(
                node_id="compare_state",
                node_type_id="core.logic.compare",
                parameters={"operator": "eq", "right_value": "succeeded"},
            ),
            WorkflowGraphNode(
                node_id="compare_gt",
                node_type_id="core.logic.compare",
                parameters={"operator": ">", "right_value": 50},
            ),
            WorkflowGraphNode(
                node_id="compare_lt",
                node_type_id="core.logic.compare",
                parameters={"operator": "<", "right_value": 80},
            ),
            WorkflowGraphNode(
                node_id="select_value",
                node_type_id="core.logic.if-else",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-task-state",
                source_node_id="task_get",
                source_port="body",
                target_node_id="extract_state",
                target_port="body",
            ),
            WorkflowGraphEdge(
                edge_id="edge-task-build",
                source_node_id="task_get",
                source_port="body",
                target_node_id="extract_build",
                target_port="body",
            ),
            WorkflowGraphEdge(
                edge_id="edge-task-version",
                source_node_id="task_get",
                source_port="body",
                target_node_id="extract_version",
                target_port="body",
            ),
            WorkflowGraphEdge(
                edge_id="edge-task-percent",
                source_node_id="task_get",
                source_port="body",
                target_node_id="extract_percent",
                target_port="body",
            ),
            WorkflowGraphEdge(
                edge_id="edge-state-compare",
                source_node_id="extract_state",
                source_port="value",
                target_node_id="compare_state",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-percent-gt",
                source_node_id="extract_percent",
                source_port="value",
                target_node_id="compare_gt",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-percent-lt",
                source_node_id="extract_percent",
                source_port="value",
                target_node_id="compare_lt",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-compare-select",
                source_node_id="compare_state",
                source_port="result",
                target_node_id="select_value",
                target_port="condition",
            ),
            WorkflowGraphEdge(
                edge_id="edge-build-select",
                source_node_id="extract_build",
                source_port="value",
                target_node_id="select_value",
                target_port="if_true",
            ),
            WorkflowGraphEdge(
                edge_id="edge-version-select",
                source_node_id="extract_version",
                source_port="value",
                target_node_id="select_value",
                target_port="if_false",
            ),
        ),
        template_inputs=(),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="selected_value",
                display_name="Selected Value",
                payload_type_id="value.v1",
                source_node_id="select_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="progress_gt",
                display_name="Progress Greater Than",
                payload_type_id="boolean.v1",
                source_node_id="compare_gt",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="progress_lt",
                display_name="Progress Less Than",
                payload_type_id="boolean.v1",
                source_node_id="compare_lt",
                source_port="result",
            ),
        ),
    )


def _build_logic_application() -> FlowApplication:
    """构造逻辑节点最小流程应用。"""

    return FlowApplication(
        application_id="logic-nodes-app",
        display_name="Logic Nodes App",
        template_ref=FlowTemplateReference(
            template_id="logic-nodes-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="selected_value",
                direction="output",
                template_port_id="selected_value",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="progress_gt",
                direction="output",
                template_port_id="progress_gt",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="progress_lt",
                direction="output",
                template_port_id="progress_lt",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )
