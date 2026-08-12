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
            """按 param group 批量执行 Muon 和 SGD 更新。"""

            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            with torch.no_grad():
                for group in self.param_groups:
                    parameters = [
                        parameter
                        for parameter in group["params"]
                        if parameter.grad is not None
                    ]
                    if not parameters:
                        continue
                    gradients = [parameter.grad for parameter in parameters]
                    if any(
                        bool(getattr(gradient, "is_sparse", False))
                        for gradient in gradients
                    ):
                        raise RuntimeError("MuSGD 不支持 sparse gradient")
                    use_muon = bool(group.get("use_muon", False))
                    for parameter in parameters:
                        state = self.state[parameter]
                        state.setdefault("momentum_buffer", torch.zeros_like(parameter))
                        if use_muon:
                            state.setdefault(
                                "momentum_buffer_SGD",
                                torch.zeros_like(parameter),
                            )
                    learning_rate = float(group["lr"])
                    momentum = float(group["momentum"])
                    nesterov = bool(group["nesterov"])
                    if use_muon:
                        muon_updates = _compute_muon_updates(
                            torch_module=torch,
                            gradients=gradients,
                            momentum_buffers=[
                                self.state[parameter]["momentum_buffer"]
                                for parameter in parameters
                            ],
                            momentum=momentum,
                            nesterov=nesterov,
                        )
                        torch._foreach_add_(
                            parameters,
                            muon_updates,
                            alpha=-(learning_rate * self.muon_weight),
                        )
                        sgd_buffers = [
                            self.state[parameter]["momentum_buffer_SGD"]
                            for parameter in parameters
                        ]
                        sgd_learning_rate = learning_rate * self.sgd_weight
                    else:
                        sgd_buffers = [
                            self.state[parameter]["momentum_buffer"]
                            for parameter in parameters
                        ]
                        sgd_learning_rate = learning_rate
                    sgd_gradients = gradients
                    weight_decay = float(group["weight_decay"])
                    if weight_decay:
                        sgd_gradients = list(
                            torch._foreach_add(
                                gradients,
                                parameters,
                                alpha=weight_decay,
                            )
                        )
                    torch._foreach_mul_(sgd_buffers, momentum)
                    torch._foreach_add_(sgd_buffers, sgd_gradients)
                    if nesterov:
                        sgd_updates = list(
                            torch._foreach_add(
                                sgd_gradients,
                                sgd_buffers,
                                alpha=momentum,
                            )
                        )
                    else:
                        sgd_updates = sgd_buffers
                    torch._foreach_add_(
                        parameters,
                        sgd_updates,
                        alpha=-sgd_learning_rate,
                    )
            return loss

    MuSGD.__name__ = "MuSGD"
    return MuSGD(param_groups)


def _compute_muon_updates(
    *,
    torch_module: Any,
    gradients: list[Any],
    momentum_buffers: list[Any],
    momentum: float,
    nesterov: bool,
) -> list[Any]:
    """批量计算 Muon 动量与 Newton-Schulz 正交更新。"""

    torch_module._foreach_mul_(momentum_buffers, momentum)
    torch_module._foreach_add_(
        momentum_buffers,
        gradients,
        alpha=1.0 - momentum,
    )
    if nesterov:
        updates = list(torch_module._foreach_mul(momentum_buffers, momentum))
        torch_module._foreach_add_(updates, gradients, alpha=1.0 - momentum)
    else:
        updates = list(momentum_buffers)
    buckets: dict[tuple[object, ...], list[tuple[int, Any, bool]]] = {}
    for index, update in enumerate(updates):
        matrix = update.reshape(len(update), -1) if update.ndim > 2 else update
        transposed = matrix.size(0) > matrix.size(1)
        if transposed:
            matrix = matrix.transpose(0, 1)
        scale = max(
            1.0,
            float(gradients[index].size(-2))
            / float(gradients[index].size(-1)),
        ) ** 0.5
        bucket_key = (
            int(matrix.size(0)),
            scale,
            matrix.device,
            matrix.dtype,
        )
        buckets.setdefault(bucket_key, []).append((index, matrix, transposed))
    for (_, scale, _, _), items in buckets.items():
        max_columns = max(int(matrix.size(1)) for _, matrix, _ in items)
        padded = torch_module.stack(
            [
                torch_module.nn.functional.pad(
                    matrix,
                    (0, max_columns - int(matrix.size(1))),
                )
                for _, matrix, _ in items
            ]
        )
        orthogonalized = _zero_power_newton_schulz(
            torch_module=torch_module,
            matrix=padded,
        ).to(gradients[items[0][0]].dtype)
        orthogonalized.mul_(scale)
        for batch_index, (update_index, matrix, transposed) in enumerate(items):
            resolved = orthogonalized[batch_index, :, : matrix.size(1)]
            if transposed:
                resolved = resolved.transpose(0, 1)
            updates[update_index] = resolved.reshape(gradients[update_index].shape)
    return updates


def _zero_power_newton_schulz(*, torch_module: Any, matrix: Any) -> Any:
    """用五步 Newton-Schulz 迭代批量近似矩阵零次幂。"""

    if matrix.ndim not in {2, 3}:
        raise ValueError("Muon 参数必须能展开成二维或三维矩阵")
    result = matrix.to(dtype=torch_module.bfloat16)
    result = result.reshape(-1, result.size(-2), result.size(-1))
    result = result / (result.norm(dim=(-2, -1), keepdim=True) + 1e-7)
    transposed = result.size(-2) > result.size(-1)
    if transposed:
        result = result.transpose(-2, -1)
    for _ in range(5):
        gram = result @ result.transpose(-2, -1)
        correction = torch_module.baddbmm(
            gram,
            gram,
            gram,
            beta=-4.7750,
            alpha=2.0315,
        )
        result = torch_module.baddbmm(
            result,
            correction,
            result,
            beta=3.4445,
        )
    if transposed:
        result = result.transpose(-2, -1)
    return result.reshape(matrix.shape)


__all__ = ["create_musgd_optimizer"]
