"""非 detection 训练共享路由支撑测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.api.rest.v1.routes.task_training import (
    catalog as catalog_module,
    responses as responses_module,
    services as services_module,
)
from backend.service.application.errors import InvalidRequestError


def test_build_summary_response_exposes_task_type_for_non_detection_training() -> None:
    """验证非 detection 训练摘要响应公开 task_type，而不是误导性的 model_type。"""

    task = SimpleNamespace(
        task_id="task-1",
        task_kind=catalog_module.YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND,
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
        task_kind=catalog_module.YOLO_TASK_SEGMENTATION_TRAINING_TASK_KIND,
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


def test_list_training_tasks_filters_by_task_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证共享列表 helper 会按 task_type 映射到对应 task_kind。"""

    captured: dict[str, object] = {}

    class _FakeTaskService:
        def __init__(self, session_factory) -> None:
            captured["session_factory"] = session_factory

        def list_tasks(self, filters):
            captured["task_kind"] = filters.task_kind
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
    assert (
        captured["task_kind"]
        == catalog_module.YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND
    )


def test_list_training_tasks_filters_by_model_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证共享列表 helper 会按公开 model_type 继续过滤结果。"""

    class _FakeTaskService:
        def __init__(self, session_factory) -> None:
            pass

        def list_tasks(self, filters):
            return (
                SimpleNamespace(
                    task_id="task-yolo11",
                    task_kind=catalog_module.YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND,
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
                SimpleNamespace(
                    task_id="task-yolov8",
                    task_kind=catalog_module.YOLO_TASK_CLASSIFICATION_TRAINING_TASK_KIND,
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
