"""YOLO11 classification 训练期评估。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.data import (
    build_yolo11_classification_training_batch,
)
from backend.service.application.models.yolo11_core.losses import (
    normalize_yolo11_classification_training_outputs,
)


def evaluate_yolo11_classification_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    batch_size: int,
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
) -> dict[str, float]:
    """对验证样本执行 YOLO11 classification 训练期评估。"""

    model.eval()
    correct_top1 = 0
    correct_top5 = 0
    total = 0
    with imports.torch.no_grad():
        for batch_start in range(0, len(samples), batch_size):
            batch = build_yolo11_classification_training_batch(
                samples=samples[batch_start : batch_start + batch_size],
                input_size=input_size,
                device=device,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            outputs = model(batch.images)
            _, probabilities = normalize_yolo11_classification_training_outputs(
                outputs=outputs,
            )
            _, top1_prediction = imports.torch.max(probabilities, 1)
            correct_top1 += int((top1_prediction == batch.targets).sum().item())
            _, topk_prediction = imports.torch.topk(
                probabilities,
                min(5, len(labels)),
                dim=1,
            )
            for index, target in enumerate(batch.targets):
                if target in topk_prediction[index]:
                    correct_top5 += 1
            total += int(batch.targets.size(0))
    model.train()
    return {
        "top1_accuracy": round(correct_top1 / max(1, total), 6) if total > 0 else 0.0,
        "top5_accuracy": round(correct_top5 / max(1, total), 6) if total > 0 else 0.0,
    }


__all__ = ["evaluate_yolo11_classification_samples"]
