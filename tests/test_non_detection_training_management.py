"""非 detection 训练共享路由支撑测试。"""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.service.api.rest.v1.routes.task_training import (
    catalog as catalog_module,
    controls as controls_module,
    output_files as output_files_module,
    responses as responses_module,
    services as services_module,
)
from backend.service.application.models.training.checkpoint_recovery import (
    expose_recoverable_latest_checkpoint,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.tasks.task_records import TaskEvent, TaskRecord
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_build_summary_response_exposes_task_type_for_non_detection_training() -> None:
    """验证非 detection 训练摘要响应公开 task_type，而不是误导性的 model_type。"""

    task = SimpleNamespace(
        task_id="task-1",
        task_kind=catalog_module.YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
        worker_pool="classification-worker",
        state="queued",
        current_attempt_no=0,
        project_id="project-1",
        display_name="classification task",
        created_by="user-1",
        created_at="2026-06-13T00:00:00Z",
        started_at=None,
        finished_at=None,
        error_message=None,
        progress={"stage": "queued"},
        result={},
        metadata={"model_type": "yolo11"},
        task_spec={"dataset_export_id": "export-1", "recipe_id": "default"},
    )

    response = responses_module.build_summary_response(task)

    assert response.task_type == "classification"
    assert response.model_type == "yolo11"
    assert response.state == "queued"
    assert response.dataset_export_id == "export-1"
    assert "task_type" in response.model_dump()
    assert response.model_dump()["model_type"] == "yolo11"


def test_build_detail_response_exposes_common_training_detail_shape() -> None:
    """验证非 detection 训练详情会补齐前端通用训练详情需要的字段。"""

    task = SimpleNamespace(
        task_id="task-2",
        task_kind=catalog_module.SEGMENTATION_TRAINING_TASK_KIND,
        worker_pool="segmentation-worker",
        state="paused",
        current_attempt_no=1,
        project_id="project-1",
        display_name="segmentation task",
        created_by="user-1",
        created_at="2026-06-13T00:00:00Z",
        started_at="2026-06-13T00:01:00Z",
        finished_at="2026-06-13T00:02:00Z",
        error_message=None,
        progress={"stage": "paused"},
        result={"latest_checkpoint_object_key": "task-runs/task-2/output-files/latest-checkpoint.pt"},
        metadata={"segmentation_training_control": {}},
        task_spec={"model_type": "yolo11", "recipe_id": "default"},
    )
    event = SimpleNamespace(
        event_id="event-1",
        task_id="task-2",
        attempt_id=None,
        event_type="status",
        created_at="2026-06-13T00:02:00Z",
        message="segmentation training paused",
        payload={"state": "paused"},
    )

    response = responses_module.build_detail_response(task, (event,))

    assert response.task_type == "segmentation"
    assert response.model_type == "yolo11"
    assert response.available_actions == ["resume", "terminate", "delete"]
    assert response.control_status.status == "idle"
    assert response.control_status.resume_checkpoint_object_key == "task-runs/task-2/output-files/latest-checkpoint.pt"
    assert response.events[0].event_id == "event-1"


def test_failed_training_with_latest_checkpoint_exposes_resume_action() -> None:
    """验证异常退出但存在完整 latest checkpoint 时允许用户恢复训练。"""

    task = SimpleNamespace(
        task_id="task-failed",
        task_kind=catalog_module.YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
        worker_pool="segmentation-worker",
        state="failed",
        current_attempt_no=0,
        project_id="project-1",
        display_name="failed segmentation task",
        created_by="user-1",
        created_at="2026-06-13T00:00:00Z",
        started_at="2026-06-13T00:01:00Z",
        finished_at="2026-06-13T00:02:00Z",
        error_message="CUDA worker exited",
        progress={"stage": "failed"},
        result={
            "latest_checkpoint_object_key": (
                "task-runs/task-failed/output-files/latest-checkpoint.pt"
            )
        },
        metadata={"yolo26_segmentation_training_control": {}},
        task_spec={"model_type": "yolo26", "recipe_id": "default"},
    )

    response = responses_module.build_detail_response(task)

    assert response.available_actions == ["resume", "delete"]
    assert response.control_status.resume_checkpoint_object_key == (
        "task-runs/task-failed/output-files/latest-checkpoint.pt"
    )


def test_checkpoint_recovery_is_exposed_only_for_complete_file(tmp_path: Path) -> None:
    """验证失败结果不会公开缺失或尚未完成写入的 checkpoint。"""

    checkpoint_path = tmp_path / "latest-checkpoint.pt"
    missing_result = expose_recoverable_latest_checkpoint(
        failed_result={"status": "failed"},
        latest_checkpoint_path=checkpoint_path,
        latest_checkpoint_object_key="task-runs/task-1/latest-checkpoint.pt",
    )
    checkpoint_path.write_bytes(b"complete checkpoint")
    available_result = expose_recoverable_latest_checkpoint(
        failed_result={"status": "failed"},
        latest_checkpoint_path=checkpoint_path,
        latest_checkpoint_object_key="task-runs/task-1/latest-checkpoint.pt",
    )

    assert "latest_checkpoint_object_key" not in missing_result
    assert missing_result.get("checkpoint_recovery_available") is None
    assert available_result == {
        "status": "failed",
        "latest_checkpoint_object_key": "task-runs/task-1/latest-checkpoint.pt",
        "checkpoint_recovery_available": True,
    }


def test_resume_failed_training_clears_terminal_state_and_enqueues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证失败任务恢复先清理终态字段，再把同一任务重新入队。"""

    checkpoint_key = "task-runs/task-failed/output-files/latest-checkpoint.pt"
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "data")))
    storage.write_bytes(checkpoint_key, b"complete checkpoint")
    task = SimpleNamespace(
        task_id="task-failed",
        task_kind=catalog_module.YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
        state="failed",
        current_attempt_no=2,
        finished_at="2026-06-13T00:02:00Z",
        error_message="worker failed",
        progress={"stage": "failed", "epoch": 41},
        result={"status": "failed", "latest_checkpoint_object_key": checkpoint_key},
        metadata={"model_type": "yolo26"},
        task_spec={"model_type": "yolo26"},
    )
    events: list[object] = []

    class _FakeTaskService:
        def __init__(self, session_factory: object) -> None:
            del session_factory

        def get_task(self, task_id: str):
            assert task_id == task.task_id
            return SimpleNamespace(task=task)

        def append_task_event(self, event):
            events.append(event)

    class _FakeQueueBackend:
        def enqueue(self, *, queue_name: str, payload: dict[str, object]):
            assert queue_name == catalog_module.YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME
            assert payload == {
                "task_id": task.task_id,
                "task_kind": task.task_kind,
                "model_type": "yolo26",
            }
            return SimpleNamespace(task_id="queue-task-resume")

    monkeypatch.setattr(controls_module, "SqlAlchemyTaskService", _FakeTaskService)

    response = controls_module.resume_training_task(
        session_factory=object(),
        dataset_storage=storage,
        queue_backend=_FakeQueueBackend(),
        task_id=task.task_id,
    )

    assert response.status == "queued"
    assert response.queue_task_id == "queue-task-resume"
    requested = events[0].payload
    assert requested["state"] == "queued"
    assert requested["attempt_no"] == 3
    assert requested["finished_at"] is None
    assert requested["error_message"] is None
    assert requested["progress"] == {"stage": "queued"}


def test_task_event_can_explicitly_clear_terminal_fields() -> None:
    """验证任务事件合并器接受 None，从失败终态恢复到 queued。"""

    task = TaskRecord(
        task_id="task-failed",
        task_kind="yolo26-segmentation-training",
        project_id="project-1",
        state="failed",
        current_attempt_no=2,
        finished_at="2026-06-13T00:02:00Z",
        error_message="worker failed",
    )
    event = TaskEvent(
        event_id="event-resume",
        task_id=task.task_id,
        event_type="status",
        created_at="2026-06-13T00:03:00Z",
        payload={
            "state": "queued",
            "attempt_no": 3,
            "finished_at": None,
            "error_message": None,
        },
    )

    updated = SqlAlchemyTaskService.__new__(SqlAlchemyTaskService)._apply_event(
        task_record=task,
        task_event=event,
    )

    assert updated.state == "queued"
    assert updated.current_attempt_no == 3
    assert updated.finished_at is None
    assert updated.error_message is None


def test_build_summary_response_resolves_training_output_files_from_summary() -> None:
    """验证摘要响应会读取 summary.output_files 中的正式训练产物路径。"""

    task = SimpleNamespace(
        task_id="task-3",
        task_kind=catalog_module.YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
        worker_pool="classification-worker",
        state="paused",
        current_attempt_no=1,
        project_id="project-1",
        display_name="classification task",
        created_by="user-1",
        created_at="2026-06-13T00:00:00Z",
        started_at="2026-06-13T00:01:00Z",
        finished_at=None,
        error_message=None,
        progress={"stage": "paused", "best_metric_value": 0.0},
        result={
            "summary": {
                "best_metric_name": "val_top1_accuracy",
                "best_metric_value": 0.0,
                "output_files": {
                    "output_object_prefix": "task-runs/task-3",
                    "latest_checkpoint_object_key": "task-runs/task-3/output-files/latest-checkpoint.pt",
                    "labels_object_key": "task-runs/task-3/output-files/labels.txt",
                    "metrics_object_key": "task-runs/task-3/output-files/train-metrics.json",
                    "validation_metrics_object_key": "task-runs/task-3/output-files/validation-metrics.json",
                    "summary_object_key": "task-runs/task-3/output-files/training-summary.json",
                },
            }
        },
        metadata={"classification_training_control": {}},
        task_spec={"model_type": "yolo11", "recipe_id": "default"},
    )

    response = responses_module.build_summary_response(task)

    assert response.output_object_prefix == "task-runs/task-3"
    assert response.latest_checkpoint_object_key == "task-runs/task-3/output-files/latest-checkpoint.pt"
    assert response.labels_object_key == "task-runs/task-3/output-files/labels.txt"
    assert response.metrics_object_key == "task-runs/task-3/output-files/train-metrics.json"
    assert response.validation_metrics_object_key == "task-runs/task-3/output-files/validation-metrics.json"
    assert response.summary_object_key == "task-runs/task-3/output-files/training-summary.json"
    assert response.best_metric_name == "val_top1_accuracy"
    assert response.best_metric_value == 0.0


def test_list_training_output_files_reads_standard_non_detection_outputs(tmp_path) -> None:
    """验证非 detection output-files helper 会按标准目录读取 ready/pending 状态。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "data"))
    )
    storage.write_json(
        "task-runs/task-4/output-files/train-metrics.json",
        {"final_metrics": {"loss": 0.2, "accuracy": 0.75}},
    )
    storage.write_json(
        "task-runs/task-4/output-files/validation-metrics.json",
        {"final_metrics": {"top1_accuracy": 0.5, "top5_accuracy": 1.0}},
    )
    storage.write_json(
        "task-runs/task-4/output-files/runtime-metrics.json",
        {
            "protocol": "training.runtime-metrics.v1",
            "runtime_history": [
                {
                    "attempt_no": 1,
                    "global_step": 10,
                    "timestamp": "2026-08-13T00:00:00+00:00",
                    "runtime": {"samples_per_second": 40.0},
                }
            ],
        },
    )
    storage.write_text("task-runs/task-4/output-files/labels.txt", "ok\nng\n")
    task = SimpleNamespace(
        task_id="task-4",
        state="running",
        result={"output_object_prefix": "task-runs/task-4"},
        metadata={},
    )

    summaries = output_files_module.list_training_output_files(
        task=task,
        dataset_storage=storage,
    )
    by_name = {item.file_name: item for item in summaries}
    labels = output_files_module.read_training_output_file_detail(
        task=task,
        dataset_storage=storage,
        file_name="labels",
    )

    assert by_name["train-metrics"].file_status == "ready"
    assert by_name["validation-metrics"].file_status == "ready"
    assert by_name["runtime-metrics"].file_status == "ready"
    assert by_name["runtime-metrics"].object_key == (
        "task-runs/task-4/output-files/runtime-metrics.json"
    )
    assert by_name["labels"].file_status == "ready"
    assert by_name["summary"].file_status == "pending"
    assert by_name["latest-checkpoint"].file_status == "pending"
    assert labels.lines == ["ok", "ng"]


def test_legacy_runtime_metrics_detail_remains_pending_after_task_completion(
    tmp_path,
) -> None:
    """验证修复前旧任务缺少 runtime 快照时详情接口不会误报 404。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "data"))
    )
    task = SimpleNamespace(
        task_id="legacy-task",
        state="succeeded",
        result={"output_object_prefix": "task-runs/legacy-task"},
        metadata={},
    )

    detail = output_files_module.read_training_output_file_detail(
        task=task,
        dataset_storage=storage,
        file_name="runtime-metrics",
    )

    assert detail.file_status == "pending"
    assert detail.object_key == (
        "task-runs/legacy-task/output-files/runtime-metrics.json"
    )


def test_list_training_tasks_filters_by_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证共享列表 helper 会按 task_type 映射到对应 task_kind。"""

    captured: dict[str, object] = {"task_kinds": []}

    class _FakeTaskService:
        def __init__(self, session_factory) -> None:
            captured["session_factory"] = session_factory

        def list_tasks(self, filters):
            captured["task_kinds"].append(filters.task_kind)
            return []

    monkeypatch.setattr(services_module, "SqlAlchemyTaskService", _FakeTaskService)

    result = services_module.list_training_tasks(
        session_factory=object(),
        project_id="project-1",
        task_type="classification",
        state="queued",
        limit=10,
    )

    assert result == []
    assert captured["task_kinds"] == [
        catalog_module.YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
        catalog_module.YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
        catalog_module.YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
    ]


def test_list_training_tasks_filters_by_model_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证共享列表 helper 会按公开 model_type 继续过滤结果。"""

    class _FakeTaskService:
        def __init__(self, session_factory) -> None:
            pass

        def list_tasks(self, filters):
            if filters.task_kind == catalog_module.YOLO11_CLASSIFICATION_TRAINING_TASK_KIND:
                return (
                    SimpleNamespace(
                        task_id="task-yolo11",
                        task_kind=catalog_module.YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
                        worker_pool="classification-worker",
                        state="queued",
                        current_attempt_no=0,
                        project_id="project-1",
                        display_name="classification yolo11",
                        created_by="user-1",
                        created_at="2026-06-13T00:00:00Z",
                        started_at=None,
                        finished_at=None,
                        error_message=None,
                        progress={},
                        result={},
                        metadata={"model_type": "yolo11"},
                        task_spec={},
                    ),
                )
            if filters.task_kind == catalog_module.YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND:
                return (
                    SimpleNamespace(
                        task_id="task-yolov8",
                        task_kind=catalog_module.YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
                        worker_pool="classification-worker",
                        state="queued",
                        current_attempt_no=0,
                        project_id="project-1",
                        display_name="classification yolov8",
                        created_by="user-1",
                        created_at="2026-06-13T00:00:01Z",
                        started_at=None,
                        finished_at=None,
                        error_message=None,
                        progress={},
                        result={},
                        metadata={"model_type": "yolov8"},
                        task_spec={},
                    ),
                )
            return (
            )

    monkeypatch.setattr(services_module, "SqlAlchemyTaskService", _FakeTaskService)

    result = services_module.list_training_tasks(
        session_factory=object(),
        project_id="project-1",
        task_type="classification",
        model_type="yolo11",
        limit=10,
    )

    assert [task.task_id for task in result] == ["task-yolo11"]


def test_list_training_tasks_rejects_unknown_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证共享列表 helper 会拒绝不受支持的 task_type。"""

    class _FakeTaskService:
        def __init__(self, session_factory) -> None:
            raise AssertionError("不应在 task_type 校验失败后继续访问任务服务")

    monkeypatch.setattr(services_module, "SqlAlchemyTaskService", _FakeTaskService)

    with pytest.raises(InvalidRequestError) as error:
        services_module.list_training_tasks(
            session_factory=object(),
            project_id="project-1",
            task_type="unknown",
        )

    assert error.value.details == {
        "task_type": "unknown",
        "supported": ["classification", "segmentation", "pose", "obb"],
    }
