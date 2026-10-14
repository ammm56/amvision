"""RF-DETR 分割头的 cuDNN 状态和并发执行回归。"""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
import torch

from backend.service.application.models.rfdetr_core.models.heads import segmentation


def _run_depthwise(x: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
    """使用分割头真实的自定义 autograd 卷积入口。"""

    return segmentation._DepthwiseConvWithoutCuDNN.apply(
        x, weight, None, (1, 1), (1, 1), (1, 1), x.shape[1]
    )


def test_cpu_depthwise_does_not_change_process_cudnn_flags(monkeypatch) -> None:
    """CPU 前向与反向不能临时修改同进程 GPU 算子的开关。"""

    def reject_flags(**_kwargs):
        raise AssertionError("CPU 卷积不应修改 cuDNN flags")

    monkeypatch.setattr(torch.backends.cudnn, "flags", reject_flags)
    x = torch.randn(1, 2, 6, 6, requires_grad=True)
    weight = torch.randn(2, 1, 3, 3, requires_grad=True)
    actual = _run_depthwise(x, weight)
    expected = torch.nn.functional.conv2d(x, weight, padding=1, groups=2)
    torch.testing.assert_close(actual, expected)
    actual_grads = torch.autograd.grad(actual.sum(), (x, weight))
    expected_grads = torch.autograd.grad(expected.sum(), (x, weight))
    for actual_grad, expected_grad in zip(actual_grads, expected_grads, strict=True):
        torch.testing.assert_close(actual_grad, expected_grad)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="需要 CUDA 验证分割头并发")
def test_cuda_depthwise_serializes_flag_changes_and_restores_on_error(monkeypatch) -> None:
    """两个分割调用不能交错恢复进程级 flags，异常也必须释放保护。"""

    first_entered = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    state_lock = threading.Lock()
    call_count = 0
    initial_enabled = torch.backends.cudnn.enabled
    x = torch.ones(1, 2, 4, 4, device="cuda")
    weight = torch.ones(2, 1, 3, 3, device="cuda")

    def controlled_conv(input_tensor, *_args, **_kwargs):
        """在已进入 flags 的卷积边界固定交错顺序，不替换保护逻辑。"""
        nonlocal call_count
        with state_lock:
            call_count += 1
            current_call = call_count
        assert not torch.backends.cudnn.enabled
        if current_call == 1:
            first_entered.set()
            assert release_first.wait(5)
            raise RuntimeError("模拟第一个卷积失败")
        second_entered.set()
        return input_tensor.clone()

    def second_call():
        """记录第二个线程已开始调用，避免把线程尚未启动误判成互斥。"""
        second_attempted.set()
        return _run_depthwise(x, weight)

    monkeypatch.setattr(segmentation.F, "conv2d", controlled_conv)
    try:
        torch.backends.cudnn.enabled = True
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(_run_depthwise, x, weight)
            try:
                assert first_entered.wait(5)
                second = executor.submit(second_call)
                assert second_attempted.wait(5)
                assert not second_entered.wait(0.1)
            finally:
                release_first.set()
            with pytest.raises(RuntimeError, match="第一个卷积失败"):
                first.result(timeout=5)
            torch.testing.assert_close(second.result(timeout=5), x)
        assert torch.backends.cudnn.enabled is True
    finally:
        torch.backends.cudnn.enabled = initial_enabled
