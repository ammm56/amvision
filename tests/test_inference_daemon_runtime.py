"""独立 inference daemon 运行资源装配测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.inference_daemon.runtime import (
    InferenceDaemonRuntime,
    build_inference_daemon_runtime,
)
from backend.inference_daemon.local_buffer_dependency import (
    LocalBufferDependencyProbe,
)
from backend.service.application.local_buffers import (
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.application.local_memory import LocalMemorySettings
from backend.service.settings import BackendServiceSettings


def test_backend_service_rejects_private_arena_as_public_main() -> None:
    """正式配置只允许唯一主图片 arena。"""

    with pytest.raises(ValueError, match="必须固定为 local-buffer-main"):
        BackendServiceSettings(
            local_buffer_broker=LocalBufferBrokerSettings(
                arena_id="unexpected-arena"
            )
        )


def test_inference_mailbox_uses_fixed_profile_and_domain_admission_config() -> None:
    """普通配置只能启停 Channel，并在领域层配置 handler admission。"""

    settings = BackendServiceSettings()
    assert settings.inference_daemon.mmap_mailbox.enabled is True
    assert settings.inference_daemon.max_concurrent_inference_requests == 16
    with pytest.raises(ValidationError, match="slot_count"):
        BackendServiceSettings(
            inference_daemon={
                "mmap_mailbox": {"enabled": True, "slot_count": 128},
            }
        )


def test_inference_daemon_uses_only_backend_main_local_buffer(
    tmp_path: Path,
) -> None:
    """验证 daemon 不创建私有 arena，并只直连 backend 主图片池。"""

    base_settings = BackendServiceSettings()
    backend_buffer_root = tmp_path / "backend-buffers"
    settings = base_settings.model_copy(
        update={
            "database": base_settings.database.model_copy(
                update={"url": f"sqlite:///{(tmp_path / 'daemon.db').as_posix()}"}
            ),
            "dataset_storage": base_settings.dataset_storage.model_copy(
                update={"root_dir": str(tmp_path / "objects")}
            ),
            "queue": base_settings.queue.model_copy(
                update={"root_dir": str(tmp_path / "queue")}
            ),
            "local_memory": LocalMemorySettings(root_dir=str(backend_buffer_root)),
            "local_buffer_broker": LocalBufferBrokerSettings(
                arena_size_bytes=16 * 1024 * 1024,
                min_block_size_bytes=1024 * 1024,
                max_allocation_bytes=8 * 1024 * 1024,
                reader_guard_slots=4,
            ),
        }
    )
    runtime = build_inference_daemon_runtime(settings)

    try:
        assert not (backend_buffer_root / "local-buffer").exists()
        for task_runtime in runtime.task_runtimes:
            sync_supervisor = task_runtime.sync_supervisor
            assert sync_supervisor.local_buffer_io is None
            assert sync_supervisor.local_buffer_broker_event_channel_provider is None
            assert sync_supervisor.local_buffer_direct_reader_settings is not None
            assert sync_supervisor.local_buffer_direct_reader_settings[
                "buffers_root"
            ] == str(backend_buffer_root.resolve())
            assert (
                sync_supervisor.local_buffer_direct_reader_settings["arena_id"]
                == "local-buffer-main"
            )

            async_supervisor = task_runtime.async_supervisor
            assert async_supervisor.local_buffer_io is None
            assert async_supervisor.local_buffer_broker_event_channel_provider is None
            assert async_supervisor.local_buffer_direct_reader_settings is None
    finally:
        runtime.session_factory.engine.dispose()


def test_inference_daemon_dependency_probe_requires_live_broker_and_valid_layout(
    tmp_path: Path,
) -> None:
    """daemon 只有在 Broker owner 和主 arena 均有效时才报告依赖就绪。"""

    settings = LocalBufferBrokerSettings(
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    probe = LocalBufferDependencyProbe(
        buffers_root=tmp_path,
        broker_settings=settings,
        layout_validation_interval_seconds=0.1,
    )
    broker = LocalBufferBrokerProcessSupervisor(
        root_dir=tmp_path,
        settings=settings,
    )

    assert probe.snapshot()["ready"] is False
    broker.start()
    try:
        assert probe.snapshot() == {
            "ready": True,
            "arena_id": "local-buffer-main",
            "error": None,
        }
    finally:
        broker.stop()
    assert probe.snapshot()["ready"] is False


def test_inference_daemon_stop_reclaims_every_component_after_one_failure() -> None:
    """验证任一 stop 失败时仍按反序回收其余组件和数据库连接。"""

    calls: list[str] = []

    class _Component:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        def stop(self) -> None:
            calls.append(self.name)
            if self.fail:
                raise RuntimeError(self.name)

    class _Engine:
        def dispose(self) -> None:
            calls.append("engine")

    runtime = InferenceDaemonRuntime(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        session_factory=SimpleNamespace(engine=_Engine()),  # type: ignore[arg-type]
        dataset_storage=SimpleNamespace(),  # type: ignore[arg-type]
        queue_backend=SimpleNamespace(),  # type: ignore[arg-type]
        task_runtimes=(
            SimpleNamespace(
                async_gateway_registry=_Component("gateway"),
                async_supervisor=_Component("async-supervisor"),
                sync_supervisor=_Component("sync-supervisor"),
            ),
        ),
        deployment_runtime_reconciler=_Component("reconciler"),  # type: ignore[arg-type]
        control_dispatcher=_Component("control", fail=True),  # type: ignore[arg-type]
        local_mmap_server=_Component("mmap"),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="control"):
        runtime.stop()

    assert calls == [
        "mmap",
        "control",
        "reconciler",
        "gateway",
        "async-supervisor",
        "sync-supervisor",
        "engine",
    ]
