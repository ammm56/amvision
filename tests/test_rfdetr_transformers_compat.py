"""RF-DETR 与 Transformers 当前配置接口的兼容测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.application.models.rfdetr_core.models.backbone.dinov2_with_windowed_attn import (
    WindowedDinov2WithRegistersBackbone,
    WindowedDinov2WithRegistersForImageClassification,
    WindowedDinov2WithRegistersModel,
)


class _ReturnDictConfig:
    """只允许读取当前 `return_dict` 属性的配置替身。"""

    return_dict = True
    output_attentions = False
    output_hidden_states = False

    @property
    def use_return_dict(self) -> bool:
        """旧属性一旦被访问就立即让测试失败。"""

        raise AssertionError("不应访问已弃用的 use_return_dict")


class _ReachedPostConfigRead(RuntimeError):
    """表示 forward 已通过默认 return_dict 解析阶段。"""


def _stop_after_return_dict_resolution(*_args, **_kwargs):
    """在配置读取后的第一个执行点停止测试。"""

    raise _ReachedPostConfigRead


def test_rfdetr_windowed_dinov2_forwards_use_current_return_dict_property() -> None:
    """三个 Transformers forward 入口均不得访问弃用配置属性。"""

    config = _ReturnDictConfig()
    with pytest.raises(ValueError, match="pixel_values"):
        WindowedDinov2WithRegistersModel.forward(
            SimpleNamespace(config=config),
            pixel_values=None,
        )

    with pytest.raises(_ReachedPostConfigRead):
        WindowedDinov2WithRegistersForImageClassification.forward(
            SimpleNamespace(
                config=config,
                dinov2_with_registers=_stop_after_return_dict_resolution,
            ),
            pixel_values=object(),
        )

    with pytest.raises(_ReachedPostConfigRead):
        WindowedDinov2WithRegistersBackbone.forward(
            SimpleNamespace(
                config=config,
                embeddings=_stop_after_return_dict_resolution,
            ),
            pixel_values=object(),
        )
