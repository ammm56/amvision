"""训练遥测跨进程 mmap ring 回归测试。"""

from __future__ import annotations

import multiprocessing
from types import SimpleNamespace

from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.models.training.training_telemetry import (
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
    publish_training_batch_telemetry,
)
from backend.service.application.models.training.training_telemetry_mmap import (
    TrainingTelemetryMmapPublisher,
    TrainingTelemetryMmapReader,
    TrainingTelemetryMmapReceiver,
)


def _point(*, step: int, loss: float) -> TrainingTelemetryPoint:
    """构建一个有效 batch 点。"""

    return TrainingTelemetryPoint(
        task_id="task-mmap-1",
        attempt_no=1,
        task_type="pose",
        model_type="yolo11",
        stage="training",
        granularity="batch",
        epoch=1,
        max_epochs=2,
        step=step,
        steps_per_epoch=4,
        global_step=step,
        total_steps=8,
        progress_percent=10.0 + step,
        learning_rate=0.001,
        metrics={"loss": loss},
        input_size=(640, 640),
    )


def _publish_from_spawned_worker(root_dir: str) -> None:
    """在真实 spawn 子进程中写入一个点。"""

    publisher = TrainingTelemetryMmapPublisher(
        root_dir=root_dir,
        min_publish_interval_seconds=0,
    )
    try:
        publisher.publish(_point(step=1, loss=0.5))
    finally:
        publisher.close()


def test_training_telemetry_mmap_ring_replays_new_points(tmp_path) -> None:
    """验证 reader 可按 producer cursor 读取后续点且 ring 保持有界。"""

    publisher = TrainingTelemetryMmapPublisher(
        root_dir=tmp_path,
        slot_count=2,
        payload_capacity_bytes=4096,
        min_publish_interval_seconds=0,
    )
    assert publisher.publish(_point(step=1, loss=3.0)) is True
    reader = TrainingTelemetryMmapReader(publisher.path)
    try:
        first = reader.read_after(session_id=None, sequence=0, limit=10)
        assert [payload["step"] for payload in first.payloads] == [1]

        assert publisher.publish(_point(step=2, loss=2.0)) is True
        assert publisher.publish(_point(step=3, loss=1.0)) is True
        replay = reader.read_after(
            session_id=first.session_id,
            sequence=first.published_sequence,
            limit=10,
        )
        assert [payload["step"] for payload in replay.payloads] == [2, 3]
        assert replay.gap_detected is False
    finally:
        reader.close()
        publisher.close()


def test_training_telemetry_mmap_receiver_forwards_worker_payload(tmp_path) -> None:
    """验证独立 worker 的 mmap 点会进入 service broker，而不写 TaskEvent。"""

    event_bus = InMemoryServiceEventBus()
    broker = TrainingTelemetryBroker(
        event_bus=event_bus,
        min_publish_interval_seconds=0,
    )
    publisher = TrainingTelemetryMmapPublisher(
        root_dir=tmp_path,
        min_publish_interval_seconds=0,
    )
    receiver = TrainingTelemetryMmapReceiver(root_dir=tmp_path, broker=broker)
    try:
        publisher.publish(_point(step=1, loss=0.75))
        assert receiver.poll_once() == 1
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert len(replay.events) == 1
        assert replay.events[0].payload["metrics"] == {"loss": 0.75}
        assert replay.events[0].payload["epoch"] == 1
    finally:
        receiver.stop()
        publisher.close()


def test_publish_bridge_uses_worker_publisher_without_local_broker() -> None:
    """验证标准独立 worker SessionFactory 会走 mmap publisher。"""

    published: list[TrainingTelemetryPoint] = []
    publisher = SimpleNamespace(publish=published.append)
    session_factory = SimpleNamespace(
        training_telemetry_broker=None,
        training_telemetry_publisher=publisher,
    )

    result = publish_training_batch_telemetry(
        session_factory=session_factory,
        task_id="task-worker-1",
        attempt_no=1,
        task_type="obb",
        model_type="yolo26",
        epoch=1,
        max_epochs=2,
        step=1,
        steps_per_epoch=3,
        global_step=1,
        total_steps=6,
        progress_percent=12.0,
        learning_rate=0.001,
        metrics={"loss": 1.25},
    )

    assert result is None
    assert len(published) == 1
    assert published[0].task_id == "task-worker-1"
    assert published[0].metrics == {"loss": 1.25}


def test_training_telemetry_mmap_crosses_spawn_process_boundary(tmp_path) -> None:
    """验证 Windows/Linux spawn worker 与 service receiver 使用真实跨进程 mmap。"""

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_publish_from_spawned_worker,
        args=(str(tmp_path),),
    )
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 0

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
    )
    receiver = TrainingTelemetryMmapReceiver(root_dir=tmp_path, broker=broker)
    try:
        assert receiver.poll_once() == 1
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert replay.events[0].payload["metrics"] == {"loss": 0.5}
        assert list(tmp_path.glob("worker-*.mmap")) == []
    finally:
        receiver.stop()
