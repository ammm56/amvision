"""YOLO classification 输出契约与交叉熵损失。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def normalize_yolo_classification_training_outputs(
    *,
    outputs: object,
    family_name: str,
) -> tuple[Any, Any | None]:
    """按 Ultralytics Classify 契约返回 ``(logits, probabilities)``。

    Classify head 在训练态返回 logits；在非 export 的评估态返回
    ``(probabilities, logits)``。这里统一两种形态，避免把评估 tuple 的
    两个元素颠倒后再把 logits 当成概率使用。
    """

    logits: Any | None = None
    probabilities: Any | None = None
    if isinstance(outputs, tuple):
        if len(outputs) >= 2:
            probabilities = outputs[0]
            logits = outputs[1]
        elif outputs:
            logits = outputs[0]
    elif isinstance(outputs, dict):
        logits = outputs.get("logits")
        probabilities = outputs.get("probabilities")
    else:
        logits = outputs

    if logits is None and probabilities is not None:
        logits = _classification_logits_from_probabilities(probabilities)
    if logits is None:
        raise InvalidRequestError(
            f"{family_name} classification 训练无法从模型输出中提取 logits"
        )
    if probabilities is None and hasattr(logits, "softmax"):
        probabilities = logits.softmax(dim=1)
    return logits, probabilities


def compute_yolo_classification_loss(
    *,
    torch_module: Any,
    outputs: object,
    targets: Any,
    family_name: str,
) -> tuple[Any, Any | None]:
    """计算 YOLO classification 多类别交叉熵损失。"""

    logits, probabilities = normalize_yolo_classification_training_outputs(
        outputs=outputs,
        family_name=family_name,
    )
    loss = torch_module.nn.functional.cross_entropy(logits, targets)
    return loss, probabilities


def _classification_logits_from_probabilities(probabilities: Any) -> Any:
    """从 softmax 概率恢复一组等价 logits。

    多类别交叉熵只与 logits 的相对差有关，因此 ``log(p)`` 是概率对应的
    正确等价表示；逐类别使用 sigmoid log-odds 会改变类别间差值。
    """

    return probabilities.clamp_min(1e-12).log()


__all__ = [
    "compute_yolo_classification_loss",
    "normalize_yolo_classification_training_outputs",
]
