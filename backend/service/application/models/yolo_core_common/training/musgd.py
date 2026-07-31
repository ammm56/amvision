"""平台自有的 MuSGD optimizer 实现。"""

from __future__ import annotations

from typing import Any


def create_musgd_optimizer(
    *,
    torch_module: Any,
    param_groups: list[dict[str, object]],
    muon_weight: float = 0.2,
    sgd_weight: float = 1.0,
) -> Any:
    """创建可由 torch 原生 state_dict 保存和恢复的 MuSGD optimizer。"""

    torch = torch_module

    class MuSGD(torch.optim.Optimizer):
        """组合 Muon 正交更新和 SGD 更新的 optimizer。"""

        def __init__(self, params: object) -> None:
            super().__init__(
                params,
                {
                    "lr": 1e-3,
                    "momentum": 0.0,
                    "weight_decay": 0.0,
                    "nesterov": False,
                    "use_muon": False,
                },
            )
            self.muon_weight = float(muon_weight)
            self.sgd_weight = float(sgd_weight)

        def step(self, closure: object | None = None) -> object | None:
            """执行一次串行 MuSGD 参数更新。"""

            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            with torch.no_grad():
                for group in self.param_groups:
                    for parameter in group["params"]:
                        if parameter.grad is None:
                            continue
                        gradient = parameter.grad
                        if getattr(gradient, "is_sparse", False):
                            raise RuntimeError("MuSGD 不支持 sparse gradient")
                        state = self.state[parameter]
                        if bool(group.get("use_muon", False)):
                            muon_buffer = state.setdefault(
                                "muon_momentum_buffer", torch.zeros_like(parameter)
                            )
                            sgd_buffer = state.setdefault(
                                "sgd_momentum_buffer", torch.zeros_like(parameter)
                            )
                            muon_update = _compute_muon_update(
                                torch_module=torch,
                                gradient=gradient,
                                momentum_buffer=muon_buffer,
                                momentum=float(group["momentum"]),
                                nesterov=bool(group["nesterov"]),
                            )
                            parameter.add_(
                                muon_update.reshape(parameter.shape),
                                alpha=-float(group["lr"]) * self.muon_weight,
                            )
                            sgd_update = _compute_sgd_update(
                                gradient=gradient,
                                parameter=parameter,
                                momentum_buffer=sgd_buffer,
                                momentum=float(group["momentum"]),
                                weight_decay=float(group["weight_decay"]),
                                nesterov=bool(group["nesterov"]),
                            )
                            parameter.add_(
                                sgd_update,
                                alpha=-float(group["lr"]) * self.sgd_weight,
                            )
                            continue
                        momentum_buffer = state.setdefault(
                            "momentum_buffer", torch.zeros_like(parameter)
                        )
                        update = _compute_sgd_update(
                            gradient=gradient,
                            parameter=parameter,
                            momentum_buffer=momentum_buffer,
                            momentum=float(group["momentum"]),
                            weight_decay=float(group["weight_decay"]),
                            nesterov=bool(group["nesterov"]),
                        )
                        parameter.add_(update, alpha=-float(group["lr"]))
            return loss

    MuSGD.__name__ = "MuSGD"
    return MuSGD(param_groups)


def _compute_muon_update(
    *,
    torch_module: Any,
    gradient: Any,
    momentum_buffer: Any,
    momentum: float,
    nesterov: bool,
) -> Any:
    """计算 Muon 动量和 Newton-Schulz 正交更新。"""

    momentum_buffer.lerp_(gradient, 1.0 - momentum)
    update = gradient.lerp(momentum_buffer, momentum) if nesterov else momentum_buffer
    if update.ndim > 2:
        update = update.reshape(len(update), -1)
    update = _zero_power_newton_schulz(torch_module=torch_module, matrix=update)
    update *= max(1.0, float(gradient.size(-2)) / float(gradient.size(-1))) ** 0.5
    return update


def _zero_power_newton_schulz(*, torch_module: Any, matrix: Any) -> Any:
    """用五步 Newton-Schulz 迭代近似矩阵零次幂。"""

    if matrix.ndim != 2:
        raise ValueError("Muon 参数必须能展开成二维矩阵")
    result = matrix.to(dtype=torch_module.bfloat16)
    result = result / (result.norm() + 1e-7)
    transposed = result.size(0) > result.size(1)
    if transposed:
        result = result.T
    for _ in range(5):
        gram = result @ result.T
        correction = -4.7750 * gram + 2.0315 * (gram @ gram)
        result = 3.4445 * result + correction @ result
    if transposed:
        result = result.T
    return result


def _compute_sgd_update(
    *,
    gradient: Any,
    parameter: Any,
    momentum_buffer: Any,
    momentum: float,
    weight_decay: float,
    nesterov: bool,
) -> Any:
    """计算与 torch SGD 一致的 momentum 更新。"""

    update_gradient = gradient.add(parameter, alpha=weight_decay) if weight_decay else gradient
    momentum_buffer.mul_(momentum).add_(update_gradient)
    if nesterov:
        return update_gradient.add(momentum_buffer, alpha=momentum)
    return momentum_buffer


__all__ = ["create_musgd_optimizer"]
