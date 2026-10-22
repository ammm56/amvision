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
