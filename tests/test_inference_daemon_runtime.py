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
from backend.service.application.local_buffers import (
    LocalBufferBrokerSettings,
)
from backend.service.application.local_memory import LocalMemorySettings
from backend.service.settings import BackendServiceSettings


def test_backend_service_rejects_private_arena_as_public_main() -> None:
    """正式 backend 配置不能把 daemon 私有 arena 暴露为主图片数据面。"""

    with pytest.raises(ValueError, match="必须固定为 local-buffer-main"):
        BackendServiceSettings(
            local_buffer_broker=LocalBufferBrokerSettings(
                arena_id="inference-daemon-private"
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


def test_inference_daemon_uses_private_async_buffer_pool_and_backend_direct_pool(
    tmp_path: Path,
) -> None:
    """验证 daemon 私有暂存池与 backend 主图片池保持独立且同时装配。"""

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
    private_broker = runtime.async_local_buffer_broker_supervisor

    try:
        assert private_broker.root_dir == (
            backend_buffer_root / "inference-daemon-private"
        )
        assert private_broker.settings.arena_id == "inference-daemon-private"
        for task_runtime in runtime.task_runtimes:
            for supervisor in (
                task_runtime.sync_supervisor,
                task_runtime.async_supervisor,
            ):
                assert supervisor.local_buffer_io is private_broker
                assert supervisor.local_buffer_broker_event_channel_provider is not None
                assert supervisor.local_buffer_direct_reader_settings is not None
                assert supervisor.local_buffer_direct_reader_settings[
                    "buffers_root"
                ] == str(backend_buffer_root.resolve())
                assert (
                    supervisor.local_buffer_direct_reader_settings["arena_id"]
                    == "local-buffer-main"
                )

        private_broker.start()
        assert private_broker.get_status()["state"] == "healthy"
    finally:
        private_broker.stop()
        runtime.session_factory.engine.dispose()


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
        async_local_buffer_broker_supervisor=_Component("private-buffer"),  # type: ignore[arg-type]
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
        "private-buffer",
        "engine",
    ]
