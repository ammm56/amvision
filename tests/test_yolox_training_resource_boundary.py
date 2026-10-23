"""核对训练返回、输出文件落盘及异常处理后的资源生命周期。"""

from __future__ import annotations

import gc
import sys
import weakref
from types import SimpleNamespace

import pytest

from backend.service.application.models.training.training_engine import (
    read_active_training_runtime,
    training_engine_entrypoint,
)
from backend.service.application.support.resource_cleanup import model_task_resource_cleanup


@pytest.mark.parametrize("exit_kind", ["success", "failure", "cancel"])
def test_training_boundary_releases_objects_after_result_consumption(
    tmp_path, monkeypatch, exit_kind,
) -> None:
    """输出 bytes 消费后和异常捕获结束后才检查引用，不把返回值当作泄漏。"""
    from backend.service.application.errors import OperationCancelledError

    calls = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: calls.append("cache"),
        ipc_collect=lambda: calls.append("ipc"),
    )))
    refs = []

    class TrainingObjects:
        """用循环引用模拟模型、optimizer 和 DataLoader 所持对象。"""

        def __init__(self):
            self.cycle = self
            self.checkpoint = b"checkpoint-data"

    @training_engine_entrypoint
    def train(request):
        """生成结果或模拟训练失败与取消，不把对象保存到外部。"""
        objects = TrainingObjects()
        refs.append(weakref.ref(objects))
        if exit_kind == "failure":
            raise RuntimeError("training failure")
        if exit_kind == "cancel":
            raise OperationCancelledError("training cancelled")
        return objects.checkpoint

    def consume():
        """模拟 service 消费 checkpoint，结束后只返回轻量标识。"""
        with model_task_resource_cleanup():
            result = train(SimpleNamespace(extra_options={"batch_mode": "fixed"}))
            (tmp_path / "checkpoint.pth").write_bytes(result)
        return "completed"

    try:
        outcome = consume()
    except (RuntimeError, OperationCancelledError):
        outcome = exit_kind
    # 异常的 traceback 离开 except 后才释放，不能在栈仍持有对象时判定泄漏。
    gc.collect()
    assert outcome == ("completed" if exit_kind == "success" else exit_kind)
    assert all(reference() is None for reference in refs)
    assert read_active_training_runtime() == {}
    assert calls.count("cache") == calls.count("ipc") == 2
    assert (tmp_path / "checkpoint.pth").exists() == (exit_kind == "success")


@pytest.mark.parametrize("exit_kind", ["failure", "service-error", "cancel"])
def test_queue_failure_cleans_after_traceback_is_released(monkeypatch, exit_kind):
    """异常处理结束后回收失败训练帧，不能只在异常仍持有模型时清理。"""
    from backend.workers.training import yolox_training_queue_worker as module
    from backend.service.application.errors import InvalidRequestError, OperationCancelledError

    refs = []
    calls = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: calls.append("cache"),
        ipc_collect=lambda: calls.append("ipc"),
    )))

    class Model:
        """包含循环引用的训练资源。"""
        def __init__(self):
            self.cycle = self

    class FailedBackend:
        """模拟 runner 清理执行时 traceback 仍然存活。"""
        def run_training(self, request):
            with model_task_resource_cleanup():
                model = Model()
                refs.append(weakref.ref(model))
                if exit_kind == "cancel":
                    raise OperationCancelledError("training cancelled")
                if exit_kind == "service-error":
                    raise InvalidRequestError("invalid training input")
                raise RuntimeError("training failed")

    task = SimpleNamespace(payload={"task_id": "test-task"}, metadata={})
    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: task)
    monkeypatch.setattr(module, "build_training_run_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "build_queue_failure_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "TrainingLeaseHeartbeat", lambda **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: task, lease_lost=False,
    ))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None,
        queue_backend=SimpleNamespace(fail=lambda *a, **kw: None, complete=lambda *a, **kw: None),
        training_backend=FailedBackend(),
    )
    # 不在断言前主动 gc；验证真实队列边界自身完成清理。
    assert worker.run_once()
    assert refs[0]() is None
    assert calls.count("cache") == calls.count("ipc") == 2


def test_idle_training_poll_does_not_clean_resources(monkeypatch):
    """空闲轮询不得触发新的 GC、Torch 导入或 CUDA 清理。"""
    from backend.workers.training import yolox_training_queue_worker as module

    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: None)
    calls = []
    monkeypatch.setattr(module, "release_model_task_resources", lambda: calls.append("cleanup"))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None, queue_backend=None,
    )
    assert not worker.run_once()
    assert not calls


def test_queue_success_cleans_after_artifact_consumption(tmp_path, monkeypatch):
    """成功任务在 checkpoint 落盘与队列确认后检查资源，不持有大返回值。"""
    from backend.workers.training import yolox_training_queue_worker as module

    refs = []
    events = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: events.append("cache"),
        ipc_collect=lambda: None,
    )))

    class ExecutionResult:
        """模拟含有待写入 checkpoint 的训练返回值。"""
        def __init__(self):
            self.cycle = self
            self.checkpoint_bytes = b"checkpoint"

    class CompletedBackend:
        """文件写入结束后只返回轻量 worker DTO。"""
        def run_training(self, request):
            result = ExecutionResult()
            refs.append(weakref.ref(result))
            (tmp_path / "best.pth").write_bytes(result.checkpoint_bytes)
            events.append("saved")
            return SimpleNamespace(**dict.fromkeys((
                "training_task_id", "status", "dataset_export_id", "dataset_export_manifest_key",
                "dataset_version_id", "format_id", "output_object_prefix", "checkpoint_object_key",
                "latest_checkpoint_object_key", "labels_object_key", "metrics_object_key",
                "validation_metrics_object_key", "summary_object_key",
            ), "test"))

    task = SimpleNamespace(payload={"task_id": "test"}, metadata={})
    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: task)
    monkeypatch.setattr(module, "build_training_run_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "TrainingLeaseHeartbeat", lambda **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: task, lease_lost=False,
    ))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None,
        queue_backend=SimpleNamespace(complete=lambda *a, **kw: events.append("completed")),
        training_backend=CompletedBackend(),
    )
    assert worker.run_once()
    assert refs[0]() is None
    assert events == ["saved", "completed", "cache"]


@pytest.mark.parametrize("exit_kind", ["success", "failure", "cancel", "stop-failure"])
def test_queue_finalization_fault_stops_consumption_and_heartbeat(monkeypatch, exit_kind):
    """持久化故障向上终止消费，不重试训练；异常栈退出后不残留训练对象。"""
    from threading import Event

    from backend.service.application.errors import OperationCancelledError
    from backend.workers.task_manager import BackgroundTaskManager, BackgroundTaskManagerConfig
    from backend.workers.training import yolox_training_queue_worker as module
    from backend.workers.training.training_lease_heartbeat import TrainingLeaseHeartbeat

    refs, heartbeats, events = [], [], []
    task = SimpleNamespace(payload={"task_id": "test"}, metadata={}, task_id="queue-test")

    class Model:
        """包含循环引用，模拟异常 traceback 持有的模型。"""
        def __init__(self):
            self.cycle = self

    class Backend:
        """模拟计算结果，不引入实际训练或磁盘副作用。"""
        def run_training(self, request):
            events.append("trained")
            model = Model()
            refs.append(weakref.ref(model))
            if exit_kind == "failure":
                raise RuntimeError("training failed")
            if exit_kind == "cancel":
                raise OperationCancelledError("cancelled")
            return SimpleNamespace(**dict.fromkeys((
                "training_task_id", "status", "dataset_export_id", "dataset_export_manifest_key",
                "dataset_version_id", "format_id", "output_object_prefix", "checkpoint_object_key",
                "latest_checkpoint_object_key", "labels_object_key", "metrics_object_key",
                "validation_metrics_object_key", "summary_object_key",
            ), "test"))

    def fail_write(*args, **kwargs):
        """模拟队列完成或失败记录无法写入，不保存异常对象。"""
        events.append("write-failed")
        raise OSError("queue persistence unavailable")

    class Heartbeat(TrainingLeaseHeartbeat):
        """使用真实启停线程，并单独覆盖停止后报错边界。"""
        def stop(self):
            message = super().stop()
            if exit_kind == "stop-failure":
                raise OSError("heartbeat stop failed")
            return message

    def heartbeat_factory(**kwargs):
        """保留 heartbeat 用于检查真实线程是否退出。"""
        heartbeat = Heartbeat(**kwargs, interval_seconds=60)
        heartbeats.append(heartbeat)
        return heartbeat

    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: task)
    monkeypatch.setattr(module, "build_training_run_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "build_queue_failure_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "TrainingLeaseHeartbeat", heartbeat_factory)
    monkeypatch.setattr(module, "release_model_task_resources", lambda: events.append("cleanup"))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None,
        queue_backend=SimpleNamespace(complete=fail_write, fail=fail_write),
        training_backend=Backend(),
    )
    manager = BackgroundTaskManager(
        consumers=(worker,),
        config=BackgroundTaskManagerConfig(max_concurrent_tasks=1, poll_interval_seconds=0.01),
    )
    stop = Event()
    with pytest.raises(OSError, match="heartbeat stop failed|queue persistence unavailable"):
        manager.run_forever(stop_event=stop)
    assert stop.is_set()
    assert len(heartbeats) == 1
    assert not heartbeats[0].is_running
    assert events.count("trained") == 1
    assert "cleanup" not in events  # 致命故障走 Worker 退出，不伪装成正常任务收尾。
    gc.collect()  # 异常已离开消费和监督栈，测试中才核对循环引用。
    assert all(reference() is None for reference in refs)


@pytest.mark.parametrize("exit_kind", ["success", "failure", "cancel"])
def test_lost_queue_lease_does_not_ack_or_fail_another_attempt(monkeypatch, exit_kind):
    """lease 丢失后仍清理资源，但不完成或覆盖其他 Worker 的新 attempt。"""
    from backend.service.application.errors import OperationCancelledError
    from backend.workers.training import yolox_training_queue_worker as module

    task = SimpleNamespace(payload={"task_id": "test"}, metadata={})
    events = []

    def train(request):
        """模拟三种任务退出方式。"""
        if exit_kind == "failure":
            raise RuntimeError("failed")
        if exit_kind == "cancel":
            raise OperationCancelledError("cancelled")
        return None

    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: task)
    monkeypatch.setattr(module, "build_training_run_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "TrainingLeaseHeartbeat", lambda **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: events.append("stopped") or task, lease_lost=True,
    ))
    monkeypatch.setattr(module, "release_model_task_resources", lambda: events.append("cleanup"))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None,
        queue_backend=SimpleNamespace(), training_backend=SimpleNamespace(run_training=train),
    )
    assert worker.run_once()
    assert events == ["stopped", "cleanup"]


def test_fatal_worker_fault_closes_runtime_resources(monkeypatch):
    """监督循环收到致命异常后标记失败并关闭 telemetry、heartbeat 和数据库。"""
    from backend.workers import main as module

    events = []

    def fatal(**kwargs):
        """代表前一测试已经覆盖的任务管理器异常传播。"""
        raise OSError("queue persistence unavailable")

    runtime = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(app_version="test")),
        workspace_dir="test", queue_backend=SimpleNamespace(root_dir="test"),
        session_factory=SimpleNamespace(engine=SimpleNamespace(dispose=lambda: events.append("dispose"))),
        training_telemetry_publisher=SimpleNamespace(
            start=lambda: events.append("telemetry-start"), close=lambda: events.append("telemetry-close"),
        ),
    )
    monkeypatch.setattr(module, "BackendWorkerBootstrap", lambda: SimpleNamespace(
        load_settings=lambda: None, build_runtime=lambda _: runtime, initialize=lambda _: None,
    ))
    monkeypatch.setattr(module, "BackendWorkerHeartbeatInfo", lambda **kw: None)
    monkeypatch.setattr(module, "BackendWorkerHeartbeat", lambda **kw: SimpleNamespace(
        start=lambda: events.append("heartbeat-start"), mark_running=lambda: None,
        assert_healthy=lambda: None, mark_failed=lambda _: events.append("failed"),
        stop=lambda: events.append("heartbeat-stop"),
    ))
    monkeypatch.setattr(module, "configure_process_training_telemetry_publisher",
                        lambda value: events.append("telemetry-unbound") if value is None else None)
    monkeypatch.setattr(module, "build_background_task_manager", lambda *a, **kw: SimpleNamespace(run_forever=fatal))
    bundle = SimpleNamespace(
        profile=SimpleNamespace(profile_id="training", enabled_consumer_kinds=("yolox-training",)),
        context=SimpleNamespace(worker_instance_id="test", topology_epoch_id="test"),
    )
    with pytest.raises(OSError, match="queue persistence unavailable"):
        module._run_worker_with_bundle(bundle)
    assert events[-5:] == ["failed", "heartbeat-stop", "telemetry-unbound", "telemetry-close", "dispose"]
