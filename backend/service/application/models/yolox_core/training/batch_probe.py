"""YOLOX AutoBatch 的带标签 loss 探针与最大多尺度输入。"""

from __future__ import annotations

import math
from typing import Any


def yolox_probe_input_size(
    input_size: tuple[int, int], multiscale_range: int
) -> tuple[int, int]:
    """返回真实多尺度采样器可能采用的最大高宽，不改变正式训练尺寸。"""

    if multiscale_range <= 0:
        return input_size
    height, width = input_size
    largest = int(height / 32) + multiscale_range
    return 32 * largest, 32 * int(largest * width / height)


def yolox_probe_training_loss(
    model: Any, images: Any, *, max_labels: int, num_classes: int
) -> Any:
    """用有界稠密标签测量真实训练 loss，覆盖标签分配、分类与框回归。

    images 由共享探针创建；targets 按配置的单图标签上限生成，不读取或改变
    训练数据，不消费随机数。正式训练仍使用数据集的真实标签。
    """

    count = max(1, int(max_labels))
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    height, width = images.shape[-2:]
    targets = images.new_tensor([
        [
            index % num_classes,
            (index % columns + 0.5) * width / columns,
            (index // columns + 0.5) * height / rows,
            width / columns * 0.8,
            height / rows * 0.8,
        ]
        for index in range(count)
    ]).unsqueeze(0).repeat(images.shape[0], 1, 1)
    # L1 尾段也计入探针，finally 恢复，不改变正式训练的阶段切换。
    was_l1 = model.head.use_l1
    try:
        model.head.use_l1 = True
        return model(images, targets)["total_loss"]
    finally:
        model.head.use_l1 = was_l1
