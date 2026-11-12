"""YOLOX 真实训练前向的 AutoBatch 适配回归。"""

from types import SimpleNamespace

import pytest
import torch

from backend.service.application.models.training.batch_policy import (
    _profile_cuda_training_batch,
    resolve_training_batch_size,
)
from backend.service.application.models.yolox_core.models.build import build_yolox_detection_model
from backend.service.application.models.yolox_core.training.batch_probe import (
    yolox_probe_input_size,
    yolox_probe_training_loss,
)


def test_probe_uses_maximum_multiscale_size() -> None:
    """探针覆盖最大尺寸，关闭多尺度时保留原尺寸。"""
    assert yolox_probe_input_size((640, 640), 5) == (800, 800)
    assert yolox_probe_input_size((640, 960), 5) == (800, 1184)
    assert yolox_probe_input_size((640, 640), 0) == (640, 640)


def test_loss_probe_restores_l1_when_forward_fails() -> None:
    """训练前向自身报错也必须恢复 L1 开关。"""
    class BrokenModel:
        """用于检查异常路径的最小 YOLOX 接口。"""
        head = SimpleNamespace(use_l1=False)

        def __call__(self, images, targets):
            """确认 targets 已提供，再模拟前向错误。"""
            assert self.head.use_l1
            assert targets.shape == (1, 4, 5)
            raise RuntimeError("forward failed")

    model = BrokenModel()
    with pytest.raises(RuntimeError, match="forward failed"):
        yolox_probe_training_loss(model, torch.zeros(1, 3, 64, 64), max_labels=4, num_classes=2)
    assert not model.head.use_l1


@pytest.mark.parametrize("mode,device,resume,expected", [
    ("fixed", "cuda:0", None, "fixed"),
    ("auto", "cpu", None, "auto-cpu-fallback"),
    ("auto", "cuda:0", 2, "resume"),
])
def test_non_probe_paths_do_not_call_training_loss(mode, device, resume, expected) -> None:
    """固定 batch、CPU 与 resume 不增加模型前向或显存探针。"""
    def forbidden_probe(images):
        """非探针路径不得调用模型 loss。"""
        raise AssertionError("unexpected training probe")

    resolution = resolve_training_batch_size(
        torch_module=SimpleNamespace(), model=SimpleNamespace(), device_name=device,
        input_size=(64, 64), dataset_size=4, requested_batch_size=2 if mode == "fixed" else None,
        default_batch_size=2, runtime_precision="fp32", extra_options={"batch_mode": mode},
        resume_batch_size=resume, training_loss_probe=forbidden_probe,
    )
    assert resolution.batch_size == 2
    assert resolution.mode == expected


@pytest.mark.parametrize("failure", [None, RuntimeError("probe failure"), torch.OutOfMemoryError("CUDA out of memory")])
def test_probe_restores_model_and_cleans_gradients(failure: Exception | None) -> None:
    """真实模型在成功、OOM、普通异常时均恢复 BN/L1，不污染正式训练。"""
    model = build_yolox_detection_model(torch_module=torch, model_scale="nano", num_classes=2)
    model.train()
    next(m for m in model.modules() if isinstance(m, torch.nn.BatchNorm2d)).eval()
    states = [m.training for m in model.modules()]
    buffers = {name: value.clone() for name, value in model.named_buffers()}
    parameters = {name: value.detach().clone() for name, value in model.named_parameters()}
    random_state = torch.get_rng_state().clone()
    cuda = SimpleNamespace(
        empty_cache=lambda: None, reset_peak_memory_stats=lambda _: None,
        synchronize=lambda _: None, max_memory_allocated=lambda _: 123,
        OutOfMemoryError=torch.OutOfMemoryError,
    )
    probe_torch = SimpleNamespace(cuda=cuda, nn=torch.nn, zeros=torch.zeros, float32=torch.float32, Tensor=torch.Tensor)

    def loss(images):
        """调用真实 YOLOX 带标签 loss 后模拟执行结果。"""
        value = yolox_probe_training_loss(model, images, max_labels=4, num_classes=2)
        if failure:
            raise failure
        assert torch.isfinite(value)
        return value

    def run():
        """CPU 复用探针逻辑，显存计量由无副作用替身提供。"""
        return _profile_cuda_training_batch(
            torch_module=probe_torch, model=model, device_name="cpu", input_size=(64, 64),
            batch_size=1, runtime_precision="fp32", training_loss_probe=loss,
        )

    if failure is not None and not isinstance(failure, torch.OutOfMemoryError):
        with pytest.raises(RuntimeError, match="probe failure"):
            run()
    else:
        assert run() == (None if failure else 123)
    assert [m.training for m in model.modules()] == states
    assert not model.head.use_l1
    assert all(p.grad is None for p in model.parameters())
    assert all(torch.equal(value, buffers[name]) for name, value in model.named_buffers())
    assert all(torch.equal(value, parameters[name]) for name, value in model.named_parameters())
    assert torch.equal(torch.get_rng_state(), random_state)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="需要 CUDA 验证真实 AutoBatch")
def test_cuda_autobatch_yolox_with_targets() -> None:
    """小尺寸真实 CUDA 训练探针必须成功解析，不再触发缺 targets 断言。"""
    model = build_yolox_detection_model(torch_module=torch, model_scale="nano", num_classes=2).cuda()
    try:
        result = resolve_training_batch_size(
            torch_module=torch, model=model, device_name="cuda:0", input_size=(64, 64),
            dataset_size=2, requested_batch_size=None, default_batch_size=1,
            runtime_precision="fp16", extra_options={"batch_mode": "auto", "batch_maximum_size": 2},
            training_loss_probe=lambda images: yolox_probe_training_loss(model, images, max_labels=4, num_classes=2),
        )
        assert result.mode == "auto-cuda-profile"
        assert result.batch_size == 2
        assert result.probed_batch_sizes == (1, 2)
    finally:
        model.cpu()
        torch.cuda.empty_cache()
