"""训练遥测迁移到通用 LocalMessage EventRing 的回归测试。"""

from __future__ import annotations

import multiprocessing
import os
from time import monotonic_ns
from types import SimpleNamespace

import pytest

from backend.contracts.ipc.local_message_profiles import EventRingChannelProfile
from backend.service.application.events import InMemoryServiceEventBus
from backend.service.application.models.training.training_telemetry import (
    TrainingTelemetryBroker,
    TrainingTelemetryPoint,
    configure_process_training_telemetry_publisher,
    publish_training_batch_telemetry,
)
from backend.service.application.models.training.training_telemetry_channel import (
    decode_training_telemetry_point,
    encode_training_telemetry_point,
)
from backend.service.infrastructure.ipc.local_message.event_ring import (
    MmapEventRingReader,
)
from backend.service.infrastructure.ipc.training_telemetry import (
    TrainingTelemetryMmapPublisher,
    TrainingTelemetryMmapReceiver,
)
from backend.service.settings import BackendServiceTrainingTelemetryConfig
from backend.workers.settings import BackendWorkerTrainingTelemetryConfig


def _profile(*, slot_count: int = 512, payload_capacity_bytes: int = 4096):
    """构造仅供边界测试使用的 EventRing profile。"""

    return EventRingChannelProfile(
        profile_id=f"training-telemetry-test-{slot_count}-{payload_capacity_bytes}",
        slot_count=slot_count,
        payload_capacity_bytes=payload_capacity_bytes,
        poll_interval_seconds=0.01,
        scan_interval_seconds=0.02,
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


def _publish_from_spawned_worker(
    buffers_root: str,
    step: int = 1,
    loss: float = 0.5,
) -> None:
    """在真实 spawn 子进程中正常关闭一个 EventRing producer。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=buffers_root,
        min_publish_interval_seconds=0,
    )
    try:
        publisher.publish(_point(step=step, loss=loss))
    finally:
        publisher.close()


def _publish_then_crash(buffers_root: str) -> None:
    """发布稳定事件后模拟 worker 未发布 closed 就退出。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=buffers_root,
        min_publish_interval_seconds=0,
    )
    publisher.publish(_point(step=1, loss=0.25))
    os._exit(0)


def test_training_telemetry_event_ring_replays_new_points_and_reports_gap(
    tmp_path,
) -> None:
    """验证通用 cursor、wrap 和 gap 语义进入业务链路。"""

    profile = _profile(slot_count=2)
    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path,
        profile=profile,
        min_publish_interval_seconds=0,
    )
    publisher.start()
    reader = MmapEventRingReader(paths=publisher.paths, profile=profile)
    try:
        assert publisher.publish(_point(step=1, loss=3.0)) is True
        first = reader.read(cursor=None, deadline_ns=monotonic_ns(), limit=10)
        assert [
            decode_training_telemetry_point(item).step  # type: ignore[union-attr]
            for item in first.events
        ] == [1]

        assert publisher.publish(_point(step=2, loss=2.0)) is True
        assert publisher.publish(_point(step=3, loss=1.0)) is True
        replay = reader.read(
            cursor=first.next_cursor,
            deadline_ns=monotonic_ns(),
            limit=10,
        )
        assert [
            decode_training_telemetry_point(item).step  # type: ignore[union-attr]
            for item in replay.events
        ] == [2, 3]
        assert replay.gap_detected is False

        for step in (4, 5, 6):
            assert publisher.publish(_point(step=step, loss=1.0 / step)) is True
        gap = reader.read(
            cursor=replay.next_cursor,
            deadline_ns=monotonic_ns(),
            limit=10,
        )
        assert gap.gap_detected is True
        assert [
            decode_training_telemetry_point(item).step  # type: ignore[union-attr]
            for item in gap.events
        ] == [5, 6]
    finally:
        reader.close(deadline_ns=monotonic_ns())
        publisher.close()


def test_training_telemetry_publisher_uses_frozen_path_and_ready_ring(tmp_path) -> None:
    """验证 worker 启动即创建统一目录下的 ready EventRing。"""

    publisher = TrainingTelemetryMmapPublisher(buffers_root=tmp_path)
    try:
        publisher.start()
        assert publisher.path == (
            tmp_path.resolve()
            / "local-message"
            / "training-telemetry"
            / f"{publisher.session_id.hex}.event.mmap"
        )
        reader = MmapEventRingReader(paths=publisher.paths, profile=publisher.profile)
        try:
            ready = reader.read(cursor=None, deadline_ns=monotonic_ns(), limit=10)
            assert ready.next_cursor.sequence == 0
            assert ready.producer_closed is False
            assert ready.events == ()
            assert reader.owner_alive() is True
        finally:
            reader.close(deadline_ns=monotonic_ns())
    finally:
        publisher.close()


def test_training_telemetry_receiver_forwards_all_business_fields(tmp_path) -> None:
    """验证 EventRing payload 逐字段进入 service broker，且不写 TaskEvent。"""

    event_bus = InMemoryServiceEventBus()
    broker = TrainingTelemetryBroker(
        event_bus=event_bus,
        min_publish_interval_seconds=0,
    )
    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path,
        min_publish_interval_seconds=0,
    )
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        publisher.publish(_point(step=1, loss=0.75))
        assert receiver.poll_once() == 1
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert len(replay.events) == 1
        payload = replay.events[0].payload
        assert payload["metrics"] == {"loss": 0.75}
        assert payload["epoch"] == 1
        assert payload["input_size"] == [640, 640]
        assert receiver.snapshot_health()[0].published_sequence == 1
    finally:
        receiver.stop()
        publisher.close()


def test_training_telemetry_receiver_survives_worker_replacement_and_locked_cleanup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Windows 旧 EventRing 瞬时占用不会阻断新 worker。"""

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(),
        min_publish_interval_seconds=0,
    )
    first_publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path,
        min_publish_interval_seconds=0,
    )
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        first_publisher.publish(_point(step=1, loss=1.0))
        assert receiver.poll_once() == 1
        first_path = first_publisher.path
        first_publisher.close()

        original_unlink = type(first_path).unlink
        blocked_once = False

        def _unlink_with_transient_windows_lock(path, *args, **kwargs) -> None:
            nonlocal blocked_once
            if path == first_path and not blocked_once:
                blocked_once = True
                raise PermissionError("simulated Windows sharing violation")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(type(first_path), "unlink", _unlink_with_transient_windows_lock)
        assert receiver.poll_once() == 0
        assert blocked_once is True
        assert first_path.exists()

        second_publisher = TrainingTelemetryMmapPublisher(
            buffers_root=tmp_path,
            min_publish_interval_seconds=0,
        )
        try:
            second_publisher.publish(_point(step=2, loss=0.5))
            assert receiver.poll_once() == 1
            assert first_path.exists() is False
            replay = broker.replay(
                task_id="task-mmap-1",
                after_cursor=None,
                limit=10,
            )
            assert [event.payload["step"] for event in replay.events] == [1, 2]
        finally:
            second_publisher.close()
    finally:
        receiver.stop()
        first_publisher.close()


def test_training_telemetry_receiver_restart_keeps_live_worker_file(tmp_path) -> None:
    """验证 service receiver 重启不清理仍由 owner lock 持有的 producer。"""

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(), min_publish_interval_seconds=0
    )
    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path, min_publish_interval_seconds=0
    )
    publisher.publish(_point(step=1, loss=1.0))
    first = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    second = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        assert first.poll_once() == 1
        first.stop()
        assert publisher.path.exists()
        assert second.poll_once() == 1
        assert publisher.path.exists()
    finally:
        first.stop()
        second.stop()
        publisher.close()


def test_training_telemetry_payload_limit_is_non_blocking(tmp_path) -> None:
    """验证 payload 超限立即返回 False，并计入 EventRing drop。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path,
        profile=_profile(payload_capacity_bytes=64),
        min_publish_interval_seconds=0,
    )
    try:
        assert publisher.publish(_point(step=1, loss=1.0)) is False
        reader = MmapEventRingReader(paths=publisher.paths, profile=publisher.profile)
        try:
            assert reader.health().dropped_total == 1
        finally:
            reader.close(deadline_ns=monotonic_ns())
    finally:
        publisher.close()


@pytest.mark.parametrize("granularity", ["batch", "epoch", "validation", "runtime"])
def test_training_telemetry_wire_mapping_keeps_all_granularities(granularity) -> None:
    """验证四种公开遥测粒度经过统一 envelope 后逐字段一致。"""

    point = _point(step=3, loss=0.125)
    point = TrainingTelemetryPoint(
        **{
            **point.__dict__,
            "granularity": granularity,
            "runtime": {"gpu_memory_bytes": 1024, "phase": "train"},
        }
    )

    decoded = decode_training_telemetry_point(encode_training_telemetry_point(point))

    assert decoded == point


def test_training_telemetry_domain_throttle_is_preserved(tmp_path) -> None:
    """验证迁移后仍按 task_id 执行业务节流，且不伪造 transport drop。"""

    publisher = TrainingTelemetryMmapPublisher(
        buffers_root=tmp_path,
        min_publish_interval_seconds=60.0,
    )
    try:
        assert publisher.publish(_point(step=1, loss=1.0)) is True
        assert publisher.publish(_point(step=2, loss=0.5)) is False
        reader = MmapEventRingReader(paths=publisher.paths, profile=publisher.profile)
        try:
            health = reader.health()
            assert health.published_sequence == 1
            assert health.dropped_total == 0
        finally:
            reader.close(deadline_ns=monotonic_ns())
    finally:
        publisher.close()


def test_training_telemetry_config_exposes_only_enable_and_domain_throttle() -> None:
    """验证路径、slot、payload、poll 和 scan 不再是普通配置面。"""

    assert BackendServiceTrainingTelemetryConfig().model_dump() == {"enabled": True}
    assert BackendWorkerTrainingTelemetryConfig().model_dump() == {
        "enabled": True,
        "min_publish_interval_seconds": 0.1,
    }
    with pytest.raises(ValueError, match="root_dir"):
        BackendServiceTrainingTelemetryConfig.model_validate(
            {"enabled": True, "root_dir": "legacy"}
        )
    with pytest.raises(ValueError, match="slot_count"):
        BackendWorkerTrainingTelemetryConfig.model_validate(
            {"enabled": True, "slot_count": 32}
        )


def test_publish_bridge_uses_worker_publisher_without_local_broker() -> None:
    """验证标准独立 worker SessionFactory 继续走进程 publisher。"""

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


def test_publish_bridge_uses_process_publisher_after_session_factory_rebuild() -> None:
    """验证执行器重建数据库工厂后仍使用 worker 进程级遥测资源。"""

    published: list[TrainingTelemetryPoint] = []
    publisher = SimpleNamespace(publish=published.append)
    rebuilt_session_factory = SimpleNamespace(
        training_telemetry_broker=None,
        training_telemetry_publisher=None,
    )
    configure_process_training_telemetry_publisher(publisher)
    try:
        publish_training_batch_telemetry(
            session_factory=rebuilt_session_factory,
            task_id="task-worker-rebuilt-session",
            attempt_no=1,
            task_type="segmentation",
            model_type="yolo11",
            epoch=1,
            max_epochs=2,
            step=1,
            steps_per_epoch=3,
            global_step=1,
            total_steps=6,
            progress_percent=12.0,
            learning_rate=0.001,
            metrics={"loss": 0.75},
        )
    finally:
        configure_process_training_telemetry_publisher(None)

    assert len(published) == 1
    assert published[0].task_id == "task-worker-rebuilt-session"


def test_training_telemetry_crosses_spawn_process_boundary(tmp_path) -> None:
    """验证 Windows/Linux spawn worker 与 service 使用真实通用 EventRing。"""

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
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        assert receiver.poll_once() == 1
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert replay.events[0].payload["metrics"] == {"loss": 0.5}
        assert list(receiver.root_dir.iterdir()) == []
    finally:
        receiver.stop()


def test_training_telemetry_supports_multiple_spawned_workers(tmp_path) -> None:
    """验证多个独立 worker 各持有 Channel，互不共享 owner、epoch 或容量。"""

    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_publish_from_spawned_worker,
            args=(str(tmp_path), step, 1.0 / step),
        )
        for step in range(1, 5)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(), min_publish_interval_seconds=0
    )
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        assert receiver.poll_once() == 4
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert sorted(event.payload["step"] for event in replay.events) == [1, 2, 3, 4]
        assert list(receiver.root_dir.iterdir()) == []
    finally:
        receiver.stop()


def test_training_telemetry_recovers_event_after_abnormal_worker_exit(tmp_path) -> None:
    """验证 producer crash 依靠 owner lock 收敛，且稳定事件不会丢失。"""

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_publish_then_crash,
        args=(str(tmp_path),),
    )
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 0
    crashed_paths = list(
        (tmp_path / "local-message" / "training-telemetry").glob("*.event.mmap")
    )
    assert len(crashed_paths) == 1
    crashed_path = crashed_paths[0]

    broker = TrainingTelemetryBroker(
        event_bus=InMemoryServiceEventBus(), min_publish_interval_seconds=0
    )
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=broker)
    try:
        assert receiver.poll_once() == 1
        replay = broker.replay(task_id="task-mmap-1", after_cursor=None, limit=10)
        assert replay.events[0].payload["metrics"] == {"loss": 0.25}
        assert not crashed_path.exists()
    finally:
        receiver.stop()
