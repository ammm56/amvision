"""YOLO26 classification loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def normalize_yolo26_classification_training_outputs(
    *,
    outputs: object,
) -> tuple[Any, Any | None]:
    """把 YOLO26 classification 训练输出规整为 logits 和 probabilities。"""

    logits: Any | None = None
    probabilities: Any | None = None
    if isinstance(outputs, tuple):
        logits = outputs[0] if outputs else None
        probabilities = outputs[1] if len(outputs) >= 2 else logits
    elif isinstance(outputs, dict):
        logits = outputs.get("logits")
        probabilities = outputs.get("probabilities", logits)
    else:
        logits = outputs

    if logits is None and probabilities is not None:
        logits = _logit_from_probability_tensor(probabilities)
    if logits is None:
        raise InvalidRequestError(
            "YOLO26 classification 训练无法从模型输出中提取 logits"
        )
    if probabilities is None and hasattr(logits, "softmax"):
        probabilities = logits.softmax(dim=1)
    return logits, probabilities


def compute_yolo26_classification_loss(
    *,
    torch_module: Any,
    outputs: object,
    targets: Any,
) -> tuple[Any, Any | None]:
    """计算 YOLO26 classification 交叉熵损失。"""

    logits, probabilities = normalize_yolo26_classification_training_outputs(
        outputs=outputs,
    )
    loss = torch_module.nn.functional.cross_entropy(logits, targets)
    return loss, probabilities


def _logit_from_probability_tensor(probabilities: Any) -> Any:
    """把概率张量转换为 BCE 风格 logits，供兼容输出使用。"""

    clamped = probabilities.clamp(1e-12, 1.0 - 1e-12)
    return (clamped / (1.0 - clamped)).log()


__all__ = [
    "compute_yolo26_classification_loss",
    "normalize_yolo26_classification_training_outputs",
]

