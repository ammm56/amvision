"""手动验证队列处理成功、失败、取消后真实 CUDA Tensor 与循环引用均释放。"""

from types import SimpleNamespace
import weakref

import pytest
import torch

from backend.service.application.errors import OperationCancelledError
from backend.service.application.runtime.device_leases import DeviceLeaseMode, DeviceLeaseProvider
from backend.service.application.support.resource_cleanup import model_task_resource_cleanup
from backend.workers.settings import get_backend_worker_settings
from backend.workers.training import yolox_training_queue_worker as module


@pytest.mark.skipif(not torch.cuda.is_available(), reason="需要 CUDA")
@pytest.mark.parametrize("exit_kind", ["failure", "cancel", "success"])
def test_cuda_queue_boundary_releases_task_tensors(monkeypatch, exit_kind):
    """独占 GPU 后在真实 CUDA 分配上核对结束资源，不影响现有推理设备租约。"""
    provider = DeviceLeaseProvider.from_config(get_backend_worker_settings().device_leases)
    refs = []

    class Resources:
        """模拟训练时具有循环引用的大 Tensor。"""
        def __init__(self):
            self.tensor = torch.zeros((1024, 1024), device="cuda:0")
            self.cycle = self

    class Backend:
        """使用真实 runner 资源上下文，错误在清理时仍持有 Tensor。"""
        def run_training(self, request):
            with model_task_resource_cleanup():
                resources = Resources()
                refs.append(weakref.ref(resources))
                if exit_kind == "failure":
                    raise RuntimeError("injected failure")
                if exit_kind == "cancel":
                    raise OperationCancelledError("injected cancel")
                return SimpleNamespace(**dict.fromkeys((
                    "training_task_id", "status", "dataset_export_id", "dataset_export_manifest_key",
                    "dataset_version_id", "format_id", "output_object_prefix", "checkpoint_object_key",
                    "latest_checkpoint_object_key", "labels_object_key", "metrics_object_key",
                    "validation_metrics_object_key", "summary_object_key",
                ), "test"))

    task = SimpleNamespace(payload={"task_id": "cuda-release-test"}, metadata={})
    monkeypatch.setattr(module, "claim_next_training_queue", lambda *a, **kw: task)
    monkeypatch.setattr(module, "build_training_run_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "build_queue_failure_metadata", lambda *a, **kw: {})
    monkeypatch.setattr(module, "TrainingLeaseHeartbeat", lambda **kw: SimpleNamespace(
        start=lambda: None, stop=lambda: task, lease_lost=False,
    ))
    worker = module.YoloXTrainingQueueWorker(
        session_factory=None, dataset_storage=None, training_backend=Backend(),
        queue_backend=SimpleNamespace(fail=lambda *a, **kw: None, complete=lambda *a, **kw: None),
    )
    with provider.acquire_cuda(
        "cuda:0", mode=DeviceLeaseMode.EXCLUSIVE, purpose="resource-test", owner_id=exit_kind,
        timeout_seconds=0,
    ):
        before = torch.cuda.memory_allocated()
        assert worker.run_once()
        assert refs[0]() is None
        assert torch.cuda.memory_allocated() == before
        assert torch.cuda.memory_reserved() == 0
