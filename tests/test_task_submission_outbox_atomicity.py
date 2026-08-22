"""业务 Task 提交路径的 Transactional Outbox 集成测试。"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.evaluation.pose_evaluation_task_service import (
    POSE_EVALUATION_QUEUE_NAME,
    PoseEvaluationTaskRequest,
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.application.tasks.queue_outbox import QueueOutboxDispatcher
from backend.service.application.tasks.queue_reference import (
    resolve_created_task_queue_reference,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)

_TASK_SUBMISSION_MODULES = (
    (
        "backend/service/application/conversions/rfdetr_conversion_task_service.py",
        "submit_conversion_task",
    ),
    (
        "backend/service/application/conversions/yolo_conversion_task_service_base.py",
        "submit_conversion_task",
    ),
    (
        "backend/service/application/models/evaluation/detection_evaluation_task_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/evaluation/obb_evaluation_task_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/evaluation/pose_evaluation_task_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/evaluation/segmentation_evaluation_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/evaluation/yolov8_classification_evaluation_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/evaluation/yolox_detection_task_service.py",
        "submit_evaluation_task",
    ),
    (
        "backend/service/application/models/inference/detection_inference_task_service.py",
        "submit_inference_task",
    ),
    (
        "backend/service/application/models/inference/task_native_inference_task_service_base.py",
        "submit_inference_task",
    ),
    (
        "backend/service/application/models/training/rfdetr_detection_task_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/segmentation_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo_detection_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolox_detection_task_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolov8_classification_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolov8_obb_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolov8_pose_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo11_classification_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo11_obb_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo11_pose_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo11_segmentation_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo26_classification_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo26_obb_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo26_pose_training_service.py",
        "submit_training_task",
    ),
    (
        "backend/service/application/models/training/yolo26_segmentation_training_service.py",
        "submit_training_task",
    ),
)

_CONTROL_CAPABLE_SUBMISSION_MODULES = {
    "backend/service/application/models/training/rfdetr_detection_task_service.py",
    "backend/service/application/models/training/yolo_detection_training_service.py",
    "backend/service/application/models/training/yolox_detection_task_service.py",
}


def test_task_submission_methods_use_outbox_without_direct_enqueue() -> None:
    """所有新 Task 提交入口必须声明 queue_submission，且不能直接 enqueue。"""

    project_root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    for relative_path, method_name in _TASK_SUBMISSION_MODULES:
        source_path = project_root / relative_path
        syntax_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        methods = [
            node
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.FunctionDef) and node.name == method_name
        ]
        if len(methods) != 1:
            failures.append(f"{relative_path}: 找到 {len(methods)} 个 {method_name}")
            continue
        method = methods[0]
        direct_enqueue_calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "enqueue"
        ]
        duplicate_event_calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append_task_event"
        ]
        queue_submission_keywords = [
            keyword
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "CreateTaskRequest"
            for keyword in node.keywords
            if keyword.arg == "queue_submission"
        ]
        if direct_enqueue_calls:
            failures.append(f"{relative_path}: {method_name} 仍直接 enqueue")
        if duplicate_event_calls:
            failures.append(f"{relative_path}: {method_name} 仍重复追加 queued event")
        if len(queue_submission_keywords) != 1:
            failures.append(
                f"{relative_path}: {method_name} 未唯一声明 queue_submission"
            )

    assert not failures, "\n".join(failures)


def test_submission_only_services_do_not_depend_on_queue_backend() -> None:
    """没有既有 Task 控制命令的提交服务不保留 QueueBackend 死依赖。"""

    project_root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    for relative_path, _method_name in _TASK_SUBMISSION_MODULES:
        if relative_path in _CONTROL_CAPABLE_SUBMISSION_MODULES:
            continue
        syntax_tree = ast.parse(
            (project_root / relative_path).read_text(encoding="utf-8")
        )
        if any(
            isinstance(node, ast.Name) and node.id == "QueueBackend"
            for node in ast.walk(syntax_tree)
        ):
            failures.append(f"{relative_path}: 仍依赖 QueueBackend")
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_require_queue_backend"
            for node in ast.walk(syntax_tree)
        ):
            failures.append(f"{relative_path}: 仍保留 _require_queue_backend")

    assert not failures, "\n".join(failures)


def test_evaluation_submission_waits_for_outbox_dispatcher_before_queue_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """业务提交只写 Task 与 Outbox，dispatcher 执行后才出现 Queue 文件。"""

    session_factory = _create_session_factory(tmp_path)
    queue_root = tmp_path / "queue"
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(queue_root))
    )
    service = _build_pose_evaluation_service(
        session_factory=session_factory,
        monkeypatch=monkeypatch,
    )

    submission = service.submit_evaluation_task(_build_request())

    assert submission.queue_name == POSE_EVALUATION_QUEUE_NAME
    assert submission.queue_task_id == f"queue-message-{submission.task_id}"
    assert (
        queue_backend.get_task(
            queue_name=submission.queue_name,
            task_id=submission.queue_task_id,
        )
        is None
    )
    assert not [path for path in queue_root.rglob("*") if path.is_file()]
    with session_factory.create_session() as session:
        unit_of_work = SqlAlchemyUnitOfWork(session)
        task_record = unit_of_work.tasks.get_task(submission.task_id)
        outbox_message = unit_of_work.queue_outbox.get_message(submission.queue_task_id)
        events = unit_of_work.tasks.list_task_events(submission.task_id)
    assert task_record is not None
    assert task_record.metadata["queue_name"] == POSE_EVALUATION_QUEUE_NAME
    assert task_record.metadata["queue_task_id"] == submission.queue_task_id
    assert outbox_message is not None
    expected_queue_payload = {"task_id": submission.task_id, "attempt_no": 1}
    assert outbox_message.payload == expected_queue_payload
    assert len(events) == 1
    assert events[0].message == "task created"

    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    assert dispatcher.dispatch_once() == 1
    queued_message = queue_backend.get_task(
        queue_name=submission.queue_name,
        task_id=submission.queue_task_id,
    )
    assert queued_message is not None
    assert queued_message.payload == expected_queue_payload
    assert [path for path in queue_root.rglob("*") if path.is_file()]


def test_queue_unavailable_does_not_mark_submitted_task_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Queue 暂时不可用只保留 Outbox 重试，不改变已提交 Task 状态。"""

    session_factory = _create_session_factory(tmp_path)
    failing_queue = _FailingQueueBackend()
    service = _build_pose_evaluation_service(
        session_factory=session_factory,
        monkeypatch=monkeypatch,
    )

    submission = service.submit_evaluation_task(_build_request())

    assert failing_queue.enqueue_count == 0
    dispatcher = QueueOutboxDispatcher(
        session_factory=session_factory,
        queue_backend=failing_queue,  # type: ignore[arg-type]
    )
    assert dispatcher.dispatch_once() == 0
    assert failing_queue.enqueue_count == 1
    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )
    assert task_detail.task.state == "queued"
    assert task_detail.task.error_message is None
    assert len(task_detail.events) == 1
    with session_factory.create_session() as session:
        unit_of_work = SqlAlchemyUnitOfWork(session)
        outbox_message = unit_of_work.queue_outbox.get_message(submission.queue_task_id)
    assert outbox_message is not None
    assert outbox_message.state == "pending"
    assert outbox_message.last_error == "queue unavailable"


@pytest.mark.parametrize(
    "metadata",
    (
        {},
        {"queue_name": "pose-evaluation"},
        {"queue_task_id": "queue-message-task-1"},
        {
            "queue_name": "pose-evaluation",
            "queue_task_id": "unexpected-message-id",
        },
    ),
)
def test_created_task_queue_reference_requires_transaction_metadata(
    metadata: dict[str, object],
) -> None:
    """新提交 Task 缺少或篡改队列 metadata 时必须暴露一致性错误。"""

    task_record = TaskRecord(
        task_id="task-1",
        task_kind="pose-evaluation",
        project_id="project-1",
        metadata=metadata,
    )

    with pytest.raises(ServiceConfigurationError):
        resolve_created_task_queue_reference(task_record)


class _FailingQueueBackend:
    """记录 enqueue 次数并模拟 Queue 暂时不可用。"""

    def __init__(self) -> None:
        self.enqueue_count = 0

    def enqueue(self, **_kwargs: object) -> object:
        """拒绝本次投递。"""

        self.enqueue_count += 1
        raise OSError("queue unavailable")


def _build_pose_evaluation_service(
    *,
    session_factory: SessionFactory,
    monkeypatch,
) -> SqlAlchemyPoseEvaluationTaskService:
    """构造只保留 Task 提交边界的 pose 评估服务。"""

    dataset_export = DatasetExport(
        dataset_export_id="dataset-export-pose-1",
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id="dataset-version-1",
        format_id="coco-keypoints-v1",
        task_type="pose",
        status="completed",
        manifest_object_key="projects/project-1/exports/pose/manifest.json",
    )
    service = SqlAlchemyPoseEvaluationTaskService(
        session_factory=session_factory,
    )
    monkeypatch.setattr(
        service,
        "_resolve_runtime_target",
        lambda _request: SimpleNamespace(model_type="yolov8"),
    )
    monkeypatch.setattr(
        service,
        "_resolve_dataset_export",
        lambda _request, *, model_type: dataset_export,
    )
    return service


def _build_request() -> PoseEvaluationTaskRequest:
    """构造最小 pose 评估提交请求。"""

    return PoseEvaluationTaskRequest(
        project_id="project-1",
        model_version_id="model-version-1",
        dataset_export_id="dataset-export-pose-1",
    )


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建完整 schema 的隔离 SQLite 数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'service-outbox.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory
