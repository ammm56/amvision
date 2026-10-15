"""转换输入可复现性和 RNG 隔离。"""

from types import SimpleNamespace

import numpy as np
import torch

from backend.service.application.models.yolo_core_common.export.execution import _build_dummy_input


def test_conversion_probe_is_fixed_without_changing_global_rng() -> None:
    """探针不能因其他代码消耗随机数而变化，也不能重置全局训练 RNG。"""
    session = SimpleNamespace(imports=SimpleNamespace(np=np, torch=torch), device_name="cpu",
                              runtime_target=SimpleNamespace(input_size=(32, 64)))
    before = torch.random.get_rng_state().clone()
    first, second = _build_dummy_input(session=session), _build_dummy_input(session=session)
    assert torch.equal(before, torch.random.get_rng_state())
    assert torch.equal(first, second)
    np.testing.assert_array_equal(first.numpy(), np.random.default_rng(0).standard_normal((1, 3, 32, 64)).astype(np.float32))
