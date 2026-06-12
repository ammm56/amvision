"""submit family workflow 示例测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.conversions.yolox_conversion_task_service import (
    YoloXConversionTaskSubmission,
)
from backend.service.application.datasets.dataset_export import DatasetExportTaskSubmission
from backend.service.application.models.yolox_evaluation_task_service import (
    YoloXEvaluationTaskSubmission,
)
from backend.service.application.models.yolox_training_service import YoloXTrainingTaskSubmission
from backend.service.application.tasks.task_service import TaskDetail
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage


@pytest.mark.parametrize(
    (
        "example_name",
        "build_method_name",
        "submit_method_name",
        "submission",
        "request_payload_value",
        "expected_request_fields",
    ),
    [
        pytest.param(
            "dataset_export_submit",
            "build_dataset_export_task_service",
            "submit_export_task",
            DatasetExportTaskSubmission(
                dataset_export_id="dataset-export-1",
                task_id="task-dataset-export-1",
                queue_name="dataset-exports",
                queue_task_id="queue-dataset-export-1",
                dataset_version_id="replace-with-dataset-version-id",
                format_id="coco-detection-v1",
                status="queued",
            ),
            {
                "project_id": "project-1",
                "dataset_id": "dataset-1",
                "dataset_version_id": "dataset-version-1",
                "format_id": "coco-detection-v1",
            },
            {
                "project_id": "project-1",
                "dataset_id": "dataset-1",
                "dataset_version_id": "dataset-version-1",
                "format_id": "coco-detection-v1",
            },
            id="dataset-export",
        ),
        pytest.param(
            "detection_training_submit",
            "build_training_task_service",
            "submit_training_task",
            YoloXTrainingTaskSubmission(
                task_id="task-training-1",
                status="queued",
                queue_name="yolox-trainings",
                queue_task_id="queue-training-1",
                dataset_export_id="replace-with-dataset-export-id",
                dataset_export_manifest_key="exports/manifest.json",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
            ),
                {
                    "project_id": "project-1",
                    "dataset_export_id": "dataset-export-1",
                    "recipe_id": "recipe-1",
                    "model_scale": "s",
                    "output_model_name": "demo-model",
                },
            {
                    "project_id": "project-1",
                    "dataset_export_id": "dataset-export-1",
                    "recipe_id": "recipe-1",
                "model_scale": "s",
                    "output_model_name": "demo-model",
            },
            id="training",
        ),
        pytest.param(
            "detection_evaluation_submit",
            "build_evaluation_task_service",
            "submit_evaluation_task",
            YoloXEvaluationTaskSubmission(
                task_id="task-evaluation-1",
                status="queued",
                queue_name="detection-evaluations",
                queue_task_id="queue-evaluation-1",
                dataset_export_id="replace-with-dataset-export-id",
                dataset_export_manifest_key="exports/manifest.json",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                model_version_id="replace-with-model-version-id",
            ),
                {
                    "project_id": "project-1",
                    "model_version_id": "model-version-1",
                    "dataset_export_id": "dataset-export-1",
                },
            {
                    "project_id": "project-1",
                    "model_version_id": "model-version-1",
                    "dataset_export_id": "dataset-export-1",
            },
            id="evaluation",
        ),
        pytest.param(
            "detection_conversion_submit",
            "build_conversion_task_service",
            "submit_conversion_task",
            YoloXConversionTaskSubmission(
                task_id="task-conversion-1",
                status="queued",
                queue_name="yolox-conversions",
                queue_task_id="queue-conversion-1",
                source_model_version_id="replace-with-source-model-version-id",
                target_formats=("onnx", "openvino-ir"),
            ),
                {
                    "project_id": "project-1",
                    "source_model_version_id": "model-version-1",
                    "target_formats": ["onnx", "openvino-ir"],
                },
            {
                    "project_id": "project-1",
                    "source_model_version_id": "model-version-1",
                "target_formats": ("onnx", "openvino-ir"),
            },
            id="conversion",
        ),
    ],
)
def test_submit_family_example_preview_runs_return_submission_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example_name: str,
    build_method_name: str,
    submit_method_name: str,
    submission: object,
    request_payload_value: dict[str, object],
    expected_request_fields: dict[str, object],
) -> None:
    """验证 submit family 正式示例可以稳定返回 submission body。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    captured: dict[str, object] = {}
    _install_fake_submit_service(
        monkeypatch=monkeypatch,
        build_method_name=build_method_name,
        submit_method_name=submit_method_name,
        submission=submission,
        captured=captured,
    )
    template, application = _load_workflow_example_documents(example_name)
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"request_payload": {"value": request_payload_value}},
        execution_metadata={"created_by": "workflow-user"},
        runtime_context=runtime_context,
    )

    assert [binding.binding_id for binding in application.bindings] == ["request_payload", "submission_body"]
    submission_body = execution_result.outputs["submission_body"]
    assert submission_body["task_id"] == getattr(submission, "task_id")
    assert submission_body["status"] == getattr(submission, "status")
    assert submission_body["queue_name"] == getattr(submission, "queue_name")
    assert submission_body["queue_task_id"] == getattr(submission, "queue_task_id")
    if "target_formats" in expected_request_fields:
        assert tuple(submission_body["target_formats"]) == tuple(getattr(submission, "target_formats"))

    request = captured["request"]
    for field_name, expected_value in expected_request_fields.items():
        actual_value = getattr(request, field_name)
        if field_name == "target_formats":
            assert tuple(actual_value) == tuple(expected_value)
            continue
        assert actual_value == expected_value
    assert captured["created_by"] == "workflow-user"
    expected_build_kwargs = {
        "build_dataset_export_task_service": {},
        "build_training_task_service": {"task_type": "detection", "model_type": "yolox"},
        "build_evaluation_task_service": {"task_type": "detection"},
        "build_conversion_task_service": {"task_type": "detection", "model_type": "yolox"},
    }
    assert captured["build_kwargs"] == expected_build_kwargs[build_method_name]


def test_detection_evaluation_package_example_preview_run_waits_and_returns_package_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 evaluation package 正式示例会提交任务、等待终态并调用独立 package 节点。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    captured: dict[str, object] = {}

    class _FakeEvaluationService:
        """记录 submit 调用的假 evaluation service。"""

        def submit_evaluation_task(self, request: object, *, created_by: str | None = None, display_name: str = ""):
            captured["submit_request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return YoloXEvaluationTaskSubmission(
                task_id="task-evaluation-1",
                status="queued",
                queue_name="detection-evaluations",
                queue_task_id="queue-evaluation-1",
                dataset_export_id="dataset-export-1",
                dataset_export_manifest_key="exports/manifest.json",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                model_version_id="model-version-1",
            )

    class _FakeTaskService:
        """返回固定 succeeded 任务详情的假 task service。"""

        def get_task(self, task_id: str, *, include_events: bool = False) -> TaskDetail:
            captured["wait_task_id"] = task_id
            captured["wait_include_events"] = include_events
            return TaskDetail(
                task=SimpleNamespace(
                    task_id=task_id,
                        task_kind="detection-evaluation",
                    display_name="evaluation package",
                    project_id="project-1",
                    created_by="workflow-user",
                    created_at="2026-05-09T00:00:00+00:00",
                    parent_task_id=None,
                    resource_profile_id=None,
                        worker_pool="detection-evaluation",
                    state="succeeded",
                    current_attempt_no=1,
                    started_at="2026-05-09T00:00:01+00:00",
                    finished_at="2026-05-09T00:00:02+00:00",
                    progress={"stage": "completed", "percent": 100.0},
                    result={
                        "map50": 0.88,
                        "map50_95": 0.71,
                        "report_object_key": "task-runs/evaluation/task-evaluation-1/artifacts/reports/evaluation-report.json",
                        "detections_object_key": "task-runs/evaluation/task-evaluation-1/artifacts/reports/detections.json",
                    },
                    error_message=None,
                    metadata={},
                    task_spec={"save_result_package": False},
                ),
                events=(),
            )

    fake_evaluation_service = _FakeEvaluationService()
    fake_task_service = _FakeTaskService()
    def _build_evaluation_task_service(self, *args, **kwargs):
        """记录 evaluation service builder 参数，并返回假 service。"""

        captured["build_args"] = args
        captured["build_kwargs"] = kwargs
        return fake_evaluation_service

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_evaluation_task_service",
        _build_evaluation_task_service,
    )
    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_task_service",
        lambda self: fake_task_service,
    )

    template, application = _load_workflow_example_documents("detection_evaluation_package")
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    dataset_storage = _create_dataset_storage(tmp_path)
    _write_dataset_storage_text(
        dataset_storage,
        "task-runs/evaluation/task-evaluation-1/artifacts/reports/evaluation-report.json",
        "{\"map50\": 0.88, \"map50_95\": 0.71}",
    )
    _write_dataset_storage_text(
        dataset_storage,
        "task-runs/evaluation/task-evaluation-1/artifacts/reports/detections.json",
        "{\"detections\": []}",
    )
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=dataset_storage,
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_payload": {
                "value": {
                    "project_id": "project-1",
                    "model_version_id": "model-version-1",
                    "dataset_export_id": "dataset-export-1",
                    "score_threshold": 0.25,
                    "nms_threshold": 0.65,
                    "save_result_package": True,
                }
            }
        },
        execution_metadata={"created_by": "workflow-user", "workflow_run_id": "run-1"},
        runtime_context=runtime_context,
    )

    assert [binding.binding_id for binding in application.bindings] == [
        "request_payload",
        "submission_body",
        "evaluation_task_detail",
        "package_body",
    ]
    submission_body = execution_result.outputs["submission_body"]
    assert submission_body["task_id"] == "task-evaluation-1"
    assert execution_result.outputs["evaluation_task_detail"]["state"] == "succeeded"
    package_body = execution_result.outputs["package_body"]
    assert package_body["task_id"] == "task-evaluation-1"
    assert package_body["package_object_key"] == (
        "workflows/runtime/run-1/package_result/model-evaluation-task-evaluation-1-result-package.zip"
    )
    package_path = dataset_storage.resolve(package_body["package_object_key"])
    assert package_path.is_file() is True
    with zipfile.ZipFile(package_path) as archive:
        assert sorted(archive.namelist()) == ["detections.json", "report.json"]

    submit_request = captured["submit_request"]
    assert submit_request.project_id == "project-1"
    assert submit_request.model_version_id == "model-version-1"
    assert submit_request.dataset_export_id == "dataset-export-1"
    assert submit_request.save_result_package is False
    assert captured["wait_task_id"] == "task-evaluation-1"
    assert captured["wait_include_events"] is False
    assert captured["build_kwargs"] == {"task_type": "detection"}


def _install_fake_submit_service(
    *,
    monkeypatch: pytest.MonkeyPatch,
    build_method_name: str,
    submit_method_name: str,
    submission: object,
    captured: dict[str, object],
) -> None:
    """把指定 submit service builder 替换为记录调用的假服务。"""

    class _FakeService:
        """记录 submit 请求并返回固定 submission。"""

        pass

    fake_service = _FakeService()

    def _submit(request: object, created_by: str | None = None, display_name: str = "") -> object:
        """记录 submit 调用，并返回预置 submission。"""

        captured["request"] = request
        captured["created_by"] = created_by
        captured["display_name"] = display_name
        return submission

    setattr(fake_service, submit_method_name, _submit)
    def _build_service(self, *args, **kwargs):
        """记录 builder 调用参数，并返回假 service。"""

        captured["build_args"] = args
        captured["build_kwargs"] = kwargs
        return fake_service

    monkeypatch.setattr(WorkflowServiceNodeRuntimeContext, build_method_name, _build_service)


def _load_workflow_example_documents(example_name: str) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """加载指定名称的 workflow 正式示例 template 与 application。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads((example_dir / f"{example_name}.template.json").read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads((example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    return template, application


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建 submit family 运行测试使用的本地数据集存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _write_dataset_storage_text(dataset_storage: LocalDatasetStorage, object_key: str, content: str) -> None:
    """向本地数据集存储写入测试文件。"""

    file_path = dataset_storage.resolve(object_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
