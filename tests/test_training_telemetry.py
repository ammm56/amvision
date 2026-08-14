"""training.telemetry.v1 broker 与 WebSocket 回归测试。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_USERNAME,
)
from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.models.training.training_telemetry import (
    TRAINING_TELEMETRY_PROTOCOL,
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
)
from backend.service.application.models.training.training_runtime_metrics_snapshot import (
    TRAINING_RUNTIME_METRICS_PROTOCOL,
    TrainingRuntimeMetricsSnapshotWriter,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def test_training_telemetry_broker_bounds_history_and_filters_non_finite_metrics() -> (
    None
):
    """验证 history 有界、cursor 缺口可见且非有限指标不会进入前端。"""

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        history_limit=2,
        max_tasks=2,
        min_publish_interval_seconds=0,
    )
    events = [
        broker.publish(
            _build_batch_point(
                step=step,
                metrics={"loss": float(step), "invalid": math.nan},
            )
        )
        for step in (1, 2, 3)
    ]
    assert all(event is not None for event in events)
    last_event = events[-1]
    assert last_event is not None
    assert last_event.payload["protocol"] == TRAINING_TELEMETRY_PROTOCOL
    assert last_event.payload["metrics"] == {"loss": 3.0}
    assert last_event.payload["invalid_metric_names"] == ["invalid"]

    replay = broker.replay(task_id="training-task-1", after_cursor=None, limit=10)
    assert [event.payload["sequence"] for event in replay.events] == [2, 3]
    assert replay.gap_detected is False
    stale = broker.replay(
        task_id="training-task-1",
        after_cursor=f"{broker.stream_session_id}:{0:020d}",
        limit=10,
    )
    assert stale.gap_detected is True


def test_training_telemetry_rejects_non_finite_public_scalars() -> None:
    """验证 NaN/Inf 不能进入学习率和进度字段。"""

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
    )
    with pytest.raises(ValueError, match="learning_rate 必须是有限数"):
        broker.publish(
            TrainingTelemetryPoint(
                **{
                    **_build_batch_point(step=1).__dict__,
                    "learning_rate": math.inf,
                }
            )
        )


def test_runtime_metrics_snapshot_persists_filters_and_compacts_full_span(
    tmp_path: Path,
) -> None:
    """验证运行时快照可跨 writer 恢复，且抽稀后保留首尾训练跨度。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    writer = TrainingRuntimeMetricsSnapshotWriter(
        storage=storage,
        history_limit=3,
        persist_interval_seconds=0,
    )
    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
        runtime_snapshot_writer=writer,
    )
    for step in (1, 2, 3, 4):
        broker.publish(
            _build_batch_point(
                step=step,
                runtime={
                    "samples_per_second": float(step * 10),
                    "gpu_utilization_percent": 70,
                    "invalid": math.nan,
                    "device": "cuda:0",
                },
            )
        )

    object_key = (
        "task-runs/training/training-task-1/artifacts/reports/runtime-metrics.json"
    )
    payload = storage.read_json(object_key)
    assert isinstance(payload, dict)
    assert payload["protocol"] == TRAINING_RUNTIME_METRICS_PROTOCOL
    assert [item["global_step"] for item in payload["runtime_history"]] == [1, 3, 4]
    assert payload["runtime_history"][-1]["runtime"] == {
        "samples_per_second": 40.0,
        "gpu_utilization_percent": 70,
    }

    resumed_writer = TrainingRuntimeMetricsSnapshotWriter(
        storage=storage,
        history_limit=3,
        persist_interval_seconds=0,
    )
    resumed_broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
        runtime_snapshot_writer=resumed_writer,
    )
    resumed_broker.publish(
        _build_batch_point(
            step=5,
            runtime={"samples_per_second": 50.0},
        )
    )
    resumed_payload = storage.read_json(object_key)
    assert isinstance(resumed_payload, dict)
    assert [
        item["global_step"] for item in resumed_payload["runtime_history"]
    ] == [1, 4, 5]


def test_runtime_metrics_snapshot_forces_the_final_batch_to_disk(tmp_path: Path) -> None:
    """验证最终 batch 不受时间节流影响，任务完成后立即具有最新快照。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
        runtime_snapshot_writer=TrainingRuntimeMetricsSnapshotWriter(
            storage=storage,
            persist_interval_seconds=3_600,
        ),
    )
    broker.publish(
        _build_batch_point(step=1, runtime={"samples_per_second": 10.0})
    )
    broker.publish(
        TrainingTelemetryPoint(
            **{
                **_build_batch_point(
                    step=2,
                    runtime={"samples_per_second": 20.0},
                ).__dict__,
                "global_step": 6,
                "total_steps": 6,
            }
        )
    )

    payload = storage.read_json(
        "task-runs/training/training-task-1/artifacts/reports/runtime-metrics.json"
    )
    assert isinstance(payload, dict)
    assert payload["runtime_history"][-1]["global_step"] == 6


def test_training_telemetry_websocket_replays_and_streams_without_task_events(
    tmp_path: Path,
) -> None:
    """验证 replay/live 走独立流，并且 batch 不增加数据库 TaskEvent。"""

    context = create_api_test_context(
        tmp_path,
        database_name="training-telemetry.db",
        enable_local_buffer_broker=False,
    )
    service = SqlAlchemyTaskService(context.session_factory)
    headers = build_test_headers(scopes="tasks:read")
    try:
        with context.client:
            task = service.create_task(
                CreateTaskRequest(
                    project_id="project-1",
                    task_kind="yolo11-training",
                    display_name="telemetry test",
                    created_by=DEFAULT_LOCAL_AUTH_USERNAME,
                )
            )
            broker = context.session_factory.training_telemetry_broker
            assert isinstance(broker, TrainingTelemetryBroker)
            broker.publish(_build_batch_point(task_id=task.task_id, step=1), force=True)

            with context.client.websocket_connect(
                f"/ws/v1/training/telemetry?task_id={task.task_id}",
                headers=headers,
            ) as websocket:
                connected = websocket.receive_json()
                replayed = websocket.receive_json()
                broker.publish(
                    _build_batch_point(task_id=task.task_id, step=2),
                    force=True,
                )
                live = websocket.receive_json()

            persisted_events = service.list_task_events(
                filters=_task_event_filters(task.task_id)
            )
        assert connected["event_type"] == "training.telemetry.connected"
        assert replayed["event_type"] == "training.batch"
        assert replayed["payload"]["step"] == 1
        assert live["payload"]["step"] == 2
        assert len(persisted_events) == 1
        assert persisted_events[0].event_type == "status"
    finally:
        context.session_factory.engine.dispose()


def _build_batch_point(
    *,
    task_id: str = "training-task-1",
    step: int,
    metrics: dict[str, float] | None = None,
    runtime: dict[str, object] | None = None,
) -> TrainingTelemetryPoint:
    """构造合法的 batch 测试点。"""

    return TrainingTelemetryPoint(
        task_id=task_id,
        attempt_no=1,
        task_type="detection",
        model_type="yolo11",
        stage="training",
        granularity="batch",
        epoch=1,
        max_epochs=2,
        step=step,
        steps_per_epoch=max(3, step),
        global_step=step,
        total_steps=6,
        progress_percent=float(step * 10),
        learning_rate=0.001,
        metrics=metrics or {"loss": float(step)},
        input_size=(640, 640),
        runtime=runtime or {},
    )


def _task_event_filters(task_id: str):
    """延迟导入查询 DTO，保持测试主体聚焦遥测协议。"""

    from backend.service.application.tasks.task_service import TaskEventQueryFilters

    return TaskEventQueryFilters(task_id=task_id, limit=100)
