"""最外层状态、训练遥测、心跳与恢复排空的生命周期回归。"""

import asyncio
import importlib
from threading import Event, current_thread, main_thread
from types import SimpleNamespace as NS

import pytest

from backend.service.application.errors import InvalidRequestError, OperationTimeoutError
from backend.service.application.service_status import ServiceStatusMonitor


def test_status_stop_preserves_active_collector_and_blocks_restart():
    """采集未结束不能报告停止，线程自行退出后也需显式确认。"""
    entered, release = Event(), Event()

    def collect():
        entered.set()
        assert release.wait(5)
        return []

    monitor = ServiceStatusMonitor(collect, "boot", max_age=.02)
    monitor.start()
    assert entered.wait(2)
    original = monitor._thread
    try:
        with pytest.raises(OperationTimeoutError):
            monitor.stop()
        assert monitor._thread is original and original.is_alive()
        assert monitor.response()[0] == 503
        with pytest.raises(InvalidRequestError):
            monitor.start()
        release.set()
        original.join(2)
        with pytest.raises(InvalidRequestError):
            monitor.start()
        monitor.stop()
        assert monitor._thread is None
        monitor.start()
        assert monitor._thread is not original
    finally:
        release.set()
        monitor.stop()


def test_status_start_failure_does_not_leave_unjoinable_thread(monkeypatch):
    """创建线程失败后，stop 仍可完成，不能留下未启动线程供 join。"""
    import backend.service.application.service_status as module

    monitor = ServiceStatusMonitor(lambda: [], "boot")

    def fail(_):
        raise RuntimeError("thread start failed")

    with monkeypatch.context() as patch:
        patch.setattr(module.Thread, "start", fail)
        with pytest.raises(RuntimeError, match="thread start failed"):
            monitor.start()
    assert monitor._thread is None
    monitor.stop()
    monitor.start()
    monitor.stop()


def test_status_self_stop_is_not_reported_as_completion():
    """线程内部请求停止不能确认自身退出，owner 必须再执行 stop。"""
    errors = []
    finished = Event()

    def collect():
        try:
            monitor.stop()
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()
        return []

    monitor = ServiceStatusMonitor(collect, "boot")
    monitor.start()
    try:
        assert finished.wait(2)
        assert len(errors) == 1 and isinstance(errors[0], OperationTimeoutError)
        with pytest.raises(InvalidRequestError):
            monitor.start()
    finally:
        monitor.stop()


@pytest.mark.parametrize("recovery", [False, True])
def test_api_never_releases_dependencies_before_status_collector(monkeypatch, tmp_path, recovery):
    """正常退出与 full 排空都必须先确认状态采集停止。"""
    module = importlib.import_module("backend.service.api.app")
    from backend.service.settings import BackendServiceSettings

    calls, controls = [], []
    entered, release = Event(), Event()
    settings = BackendServiceSettings()
    runtime = NS(settings=settings)

    class Bootstrap:
        def __init__(self, **_):
            pass

        def load_settings(self):
            return settings

        def build_runtime(self, _):
            return runtime

        def initialize(self, _):
            pass

        def start_runtime(self, _):
            pass

        def stop_runtime(self, _):
            calls.append("stop")

        def drain_runtime(self, _, *, strict):
            assert strict
            calls.append("drain")

        def bind_application_state(self, *_):
            pass

    class Control:
        phase = "ready"

        def __init__(self, directory, liveness, drain, shutdown, **_):
            self.drain = drain
            controls.append(self)

        def start(self):
            pass

        def close(self):
            pass

        def publish(self, *_):
            pass

    def collect():
        entered.set()
        assert release.wait(5)
        return []

    monitor = ServiceStatusMonitor(collect, "boot", max_age=.02)
    monkeypatch.setattr(module, "BackendServiceBootstrap", Bootstrap)
    monkeypatch.setattr(module, "ServiceStatusCollector", lambda _: collect)
    monkeypatch.setattr(module, "ServiceStatusMonitor", lambda *_: monitor)
    monkeypatch.setattr(module, "HttpRecoveryControl", Control)
    monkeypatch.setenv("AMVISION_HTTP_RECOVERY_DIR", str(tmp_path))
    app = module.create_app()

    async def run():
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        assert entered.wait(2)
        try:
            if recovery:
                with pytest.raises(OperationTimeoutError):
                    controls[0].drain()
                assert calls == []
            else:
                with pytest.raises(OperationTimeoutError):
                    await context.__aexit__(None, None, None)
                assert calls == []
        finally:
            release.set()
            if recovery:
                await context.__aexit__(None, None, None)
            monitor.stop()

    asyncio.run(run())


def test_training_telemetry_stop_keeps_reader_until_receiver_exits(tmp_path, monkeypatch):
    """接收线程卡在 broker 时，不能提前关闭仍被访问的 reader。"""
    from backend.service.infrastructure.ipc.training_telemetry import TrainingTelemetryMmapReceiver

    entered, release = Event(), Event()
    closed = []
    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=object())
    monkeypatch.setattr(receiver, "_discover_readers", lambda: None)

    def poll():
        entered.set()
        assert release.wait(10)

    monkeypatch.setattr(receiver, "_poll_readers", poll)
    receiver._readers[tmp_path] = NS(reader=NS(close=lambda **_: closed.append(True)))
    receiver.start()
    original = receiver._thread
    assert entered.wait(2)
    try:
        with pytest.raises(OperationTimeoutError):
            receiver.stop()
        assert not closed and receiver._thread is original
        assert not receiver.is_running
        with pytest.raises(InvalidRequestError):
            receiver.start()
        release.set()
        original.join(2)
        with pytest.raises(InvalidRequestError):
            receiver.start()
        receiver.stop()
        assert closed == [True]
        assert receiver._thread is None
    finally:
        release.set()
        receiver.stop()


def test_training_telemetry_failed_reader_close_blocks_restart(tmp_path):
    """资源清理失败也必须封闭恢复，即使接收线程已经不存在。"""
    from backend.service.infrastructure.ipc.training_telemetry import TrainingTelemetryMmapReceiver

    receiver = TrainingTelemetryMmapReceiver(buffers_root=tmp_path, broker=object())
    failure = [True]

    def close(**_):
        if failure[0]:
            raise OSError("reader close failed")

    receiver._readers[tmp_path] = NS(reader=NS(close=close))
    with pytest.raises(OSError, match="reader close failed"):
        receiver.stop()
    try:
        with pytest.raises(InvalidRequestError):
            receiver.start()
    finally:
        failure[0] = False
        receiver.stop()


def test_worker_heartbeat_cannot_publish_stopped_before_writer_exits(tmp_path, monkeypatch):
    """保留在途心跳归属，不能先写 stopped 再被旧线程覆盖。"""
    from backend.workers.health import BackendWorkerHeartbeat, BackendWorkerHeartbeatInfo
    from tests.test_backend_worker_health import _activate_topology, _launch_bundle, _profile

    profile = _profile("dataset-import", "dataset-import")
    layout, topology = _activate_topology(tmp_path, profile)
    info = BackendWorkerHeartbeatInfo(
        launch_bundle=_launch_bundle(layout=layout, topology=topology, profile=profile),
        app_version="0.1.8", workspace_dir=tmp_path, queue_root_dir=tmp_path,
    )
    heartbeat = BackendWorkerHeartbeat(info=info, interval_seconds=.5)
    entered, release = Event(), Event()
    snapshots = []

    def write():
        if current_thread() is not main_thread():
            entered.set()
            assert release.wait(10)
        snapshots.append(heartbeat._status)

    monkeypatch.setattr(heartbeat, "_write_snapshot", write)
    heartbeat.start()
    original = heartbeat._thread
    assert entered.wait(2)
    try:
        with pytest.raises(RuntimeError, match="退出"):
            heartbeat.stop()
        assert heartbeat._thread is original and "stopped" not in snapshots
        release.set()
        original.join(2)
        with pytest.raises(RuntimeError, match="停止"):
            heartbeat.start()
        heartbeat.stop()
        assert heartbeat._thread is None and snapshots[-1] == "stopped"
    finally:
        release.set()
        heartbeat.stop()
