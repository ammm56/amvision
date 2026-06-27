"""普通 YOLO 训练使用的 EMA 权重平滑。"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


class YoloModelEMA:
    """维护一份跟随训练模型更新的 EMA 模型。"""

    def __init__(
        self,
        *,
        model: Any,
        decay: float = 0.9999,
        tau: float = 2000.0,
        updates: int = 0,
    ) -> None:
        """按 Ultralytics EMA 规则初始化平滑模型。"""

        self.model = deepcopy(model).eval()
        self.decay = float(decay)
        self.tau = float(tau)
        self.updates = max(0, int(updates))
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def update(self, model: Any) -> None:
        """在 optimizer step 后用当前训练模型更新 EMA 权重。"""

        self.updates += 1
        decay = self._current_decay()
        model_state = model.state_dict()
        ema_state = self.model.state_dict()
        for name, ema_value in ema_state.items():
            source_value = model_state.get(name)
            if source_value is None or not getattr(
                getattr(ema_value, "dtype", None),
                "is_floating_point",
                False,
            ):
                continue
            ema_value.mul_(decay)
            ema_value.add_(
                source_value.detach().to(
                    device=ema_value.device,
                    dtype=ema_value.dtype,
                ),
                alpha=1.0 - decay,
            )

    def state_dict(self) -> dict[str, Any]:
        """返回 EMA 模型 state_dict。"""

        return dict(self.model.state_dict())

    def load_state_dict(
        self,
        state_dict: dict[str, Any],
        *,
        strict: bool = False,
    ) -> None:
        """从 checkpoint 恢复 EMA state_dict。"""

        self.model.load_state_dict(state_dict, strict=strict)

    def _current_decay(self) -> float:
        """计算当前更新步对应的 EMA decay。"""

        return self.decay * (1.0 - math.exp(-float(self.updates) / self.tau))


__all__ = ["YoloModelEMA"]
