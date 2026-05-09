"""workflow task.get 节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.tasks.task_service import CreateTaskRequest, SqlAlchemyTaskService
from backend.service.application.workflows.runtime_service import (
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import BackendServiceSettings
from tests.test_workflow_runtime_sanitization import _FakeWorkerManager
from tests.test_workflow_runtime_sanitization import _build_runtime_service as _build_base_runtime_service


def test_preview_run_task_get_node_reads_existing_task_detail(tmp_path: Path) -> None:
    """验证 task.get 节点可以在 preview run 中返回任务详情。"""

    service, _, session_factory = _build_task_runtime_service(tmp_path)
    task_record = SqlAlchemyTaskService(session_factory).create_task(
        CreateTaskRequest(
            project_id="project-1",
            task_kind="demo-task",
            display_name="Demo Task",
            created_by="tester",
            task_spec={"dataset_id": "dataset-1"},
            metadata={"source": "unit-test"},
        )
    )

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_task_get_application(),
            template=_build_task_get_template(task_id=task_record.task_id),
            input_bindings={},
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    body = preview_run.outputs["task_body"]
    assert body["task_id"] == task_record.task_id
    assert body["task_kind"] == "demo-task"
    assert body["task_spec"]["dataset_id"] == "dataset-1"
    assert body["events"][0]["event_type"] == "status"


def _build_task_runtime_service(
    tmp_path: Path,
) -> tuple[WorkflowRuntimeService, LocalWorkflowJsonService, object]:
    """构造支持 task.get 节点测试的 runtime service。"""

    service, workflow_service, node_catalog_registry = _build_base_runtime_service(tmp_path)
    return service, workflow_service, service.session_factory


def _build_task_get_template(*, task_id: str) -> WorkflowGraphTemplate:
    """构造 task.get 最小模板。"""

    return WorkflowGraphTemplate(
        template_id="task-get-template",
        template_version="1.0.0",
        display_name="Task Get Template",
        nodes=(
            WorkflowGraphNode(
                node_id="task_get",
                node_type_id="core.service.task.get",
                parameters={
                    "task_id": task_id,
                    "include_events": True,
                },
            ),
        ),
        edges=(),
        template_inputs=(),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="task_body",
                display_name="Task Body",
                payload_type_id="response-body.v1",
                source_node_id="task_get",
                source_port="body",
            ),
        ),
    )


def _build_task_get_application() -> FlowApplication:
    """构造 task.get 最小流程应用。"""

    return FlowApplication(
        application_id="task-get-app",
        display_name="Task Get App",
        template_ref=FlowTemplateReference(
            template_id="task-get-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="task_body",
                direction="output",
                template_port_id="task_body",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "response-body.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )