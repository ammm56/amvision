"""workflow task.wait 节点测试。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
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


def test_preview_run_task_wait_node_blocks_until_task_reaches_terminal_state(tmp_path: Path) -> None:
    """验证 task.wait 节点会等待任务进入终态并返回最终详情。"""

    service, _, _ = _build_runtime_service(tmp_path)
    task_service = SqlAlchemyTaskService(service.session_factory)
    task_record = task_service.create_task(
        CreateTaskRequest(
            project_id="project-1",
            task_kind="demo-task",
            display_name="Demo Wait Task",
            created_by="tester",
        )
    )

    def _finish_task() -> None:
        time.sleep(0.2)
        task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_record.task_id,
                event_type="result",
                message="task finished",
                payload={
                    "state": "succeeded",
                    "result": {
                        "model_version_id": "model-version-1",
                        "model_build_id": "model-build-1",
                    },
                },
            )
        )

    worker = threading.Thread(target=_finish_task, daemon=True)
    worker.start()
    try:
        preview_run = service.create_preview_run(
            WorkflowPreviewRunCreateRequest(
                project_id="project-1",
                application=_build_task_wait_application(),
                template=_build_task_wait_template(task_id=task_record.task_id),
                input_bindings={},
                timeout_seconds=5,
            ),
            created_by="workflow-user",
        )
    finally:
        worker.join(timeout=2)

    assert preview_run.state == "succeeded"
    body = preview_run.outputs["task_body"]
    assert body["task_id"] == task_record.task_id
    assert body["state"] == "succeeded"
    assert body["result"]["model_version_id"] == "model-version-1"
    assert body["result"]["model_build_id"] == "model-build-1"


def _build_task_wait_template(*, task_id: str) -> WorkflowGraphTemplate:
    """构造 task.wait 最小模板。"""

    return WorkflowGraphTemplate(
        template_id="task-wait-template",
        template_version="1.0.0",
        display_name="Task Wait Template",
        nodes=(
            WorkflowGraphNode(
                node_id="task_wait",
                node_type_id="core.service.task.wait",
                parameters={
                    "task_id": task_id,
                    "timeout_seconds": 2,
                    "poll_interval_seconds": 0.05,
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
                source_node_id="task_wait",
                source_port="body",
            ),
        ),
    )


def _build_task_wait_application() -> FlowApplication:
    """构造 task.wait 最小流程应用。"""

    return FlowApplication(
        application_id="task-wait-app",
        display_name="Task Wait App",
        template_ref=FlowTemplateReference(
            template_id="task-wait-template",
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