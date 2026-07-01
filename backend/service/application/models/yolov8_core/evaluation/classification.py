"""YOLOv8 classification 训练期快速评估。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.training import (
    YoloClassificationDataLoaderPlan,
    build_yolo_classification_training_dataloader,
    load_yolo_classification_dataloader_imports,
    move_yolo_classification_batch_to_device,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_classification_training_batch,
)
from backend.service.application.models.yolov8_core.losses import (
    normalize_yolov8_classification_training_outputs,
)


def evaluate_yolov8_classification_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    batch_size: int,
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    dataloader_plan: YoloClassificationDataLoaderPlan | None = None,
) -> dict[str, float]:
    """对验证样本执行 YOLOv8 classification 训练期评估。"""

    plan = dataloader_plan or YoloClassificationDataLoaderPlan(
        num_workers=0,
        pin_memory=str(device).startswith("cuda"),
        prefetch_factor=4,
        persistent_workers=False,
        seed=100_000,
    )
    validation_dataloader = build_yolo_classification_training_dataloader(
        torch_module=imports.torch,
        samples=samples,
        batch_size=batch_size,
        input_size=input_size,
        augmentation_options=None,
        plan=plan,
        shuffle=False,
        build_batch=build_yolov8_classification_training_batch,
        load_imports=load_yolo_classification_dataloader_imports,
    )
    previous_training_mode = bool(model.training)
    model.eval()
    correct_top1 = 0
    correct_top5 = 0
    total = 0
    with imports.torch.no_grad():
        for cpu_batch in validation_dataloader:
            if cpu_batch is None:
                continue
            batch = move_yolo_classification_batch_to_device(
                batch=cpu_batch,
                device=device,
                precision=precision,
                torch_module=imports.torch,
            )
            outputs = model(batch.images)
            _, probabilities = normalize_yolov8_classification_training_outputs(
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
    model.train(previous_training_mode)
    return {
        "top1_accuracy": round(correct_top1 / max(1, total), 6) if total > 0 else 0.0,
        "top5_accuracy": round(correct_top5 / max(1, total), 6) if total > 0 else 0.0,
    }


__all__ = ["evaluate_yolov8_classification_samples"]
