from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import torch
import torchvision.transforms as T  # noqa: N812
from matplotlib.axes import Axes
from torch.utils.data import DataLoader

from backend.service.application.models.rfdetr_core import supervision_compat as sv
from backend.service.application.models.rfdetr_core.utilities.box_ops import box_cxcywh_to_xyxy
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


class DatasetGridSaver:
    """RF-DETR core 类：`DatasetGridSaver`。"""

    def __init__(
        self, data_loader: DataLoader, output_dir: Path, max_batches: int = 3, dataset_type: str = "train"
    ) -> None:
        self.data_loader = data_loader
        self.output_dir = output_dir
        self.max_batches = max_batches
        self.dataset_type = dataset_type
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_grid(self) -> None:
        """执行 `save_grid`。
        
        返回：
        - 当前函数的执行结果。
        """
        inv_normalize = T.Normalize(
            mean=[-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225],
            std=[1 / 0.229, 1 / 0.224, 1 / 0.225],
        )
        box_annotator = sv.BoxAnnotator(thickness=2)
        label_annotator = sv.LabelAnnotator(
            text_color=sv.Color.BLACK,
            text_scale=0.5,
            text_padding=3,
        )

        for batch_idx, (sample, target) in enumerate(self.data_loader):
            if batch_idx >= self.max_batches:
                break

            fig, axes = plt.subplots(3, 3, figsize=(12, 12))
            fig.suptitle(f"{self.dataset_type} dataset, batch {batch_idx}")
            axes = axes.flatten()

            sample_index = 0
            for sample_index, (single_image, single_target) in enumerate(zip(sample.tensors, target)):
                if sample_index >= 9:
                    break
                self._annotate_and_plot(
                    single_image, single_target, axes[sample_index], inv_normalize, box_annotator, label_annotator
                )

            for i in range(sample_index, 9):
                axes[i].axis("off")

            fig.tight_layout()
            plt.savefig(self.output_dir / f"{self.dataset_type}_batch{batch_idx}_grid.jpg", dpi=200)
            plt.close()

        logger.info(f"Saved {self.dataset_type} grids with augmented images to: {self.output_dir.resolve()}")

    @staticmethod
    def _annotate_and_plot(
        single_image: torch.Tensor,
        single_target: dict[str, Any],
        ax: Axes,
        inv_normalize: T.Normalize,
        box_annotator: sv.BoxAnnotator,
        label_annotator: sv.LabelAnnotator,
    ) -> None:
        """执行 `_annotate_and_plot`。
        
        参数：
        - `single_image`：传入的 `single_image` 参数。
        - `single_target`：传入的 `single_target` 参数。
        - `ax`：传入的 `ax` 参数。
        - `inv_normalize`：传入的 `inv_normalize` 参数。
        - `box_annotator`：传入的 `box_annotator` 参数。
        - `label_annotator`：传入的 `label_annotator` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        from PIL import Image as PILImage

        resized_size = single_target["size"]
        if isinstance(resized_size, torch.Tensor):
            resized_size = resized_size.detach().cpu()
        h, w = int(resized_size[0]), int(resized_size[1])

        de_normalized_img = inv_normalize(single_image)
        if isinstance(de_normalized_img, torch.Tensor):
            de_normalized_img = de_normalized_img.detach().cpu().numpy()
        scene = PILImage.fromarray((np.clip(de_normalized_img.transpose(1, 2, 0), 0.0, 1.0) * 255).astype(np.uint8))

        if len(single_target["boxes"]) > 0:
            labels_tensor = single_target["labels"]
            if isinstance(labels_tensor, torch.Tensor):
                class_ids = labels_tensor.detach().cpu().numpy().astype(int)
            else:
                class_ids = np.asarray(labels_tensor, dtype=int)

            boxes = single_target["boxes"]
            if isinstance(boxes, torch.Tensor):
                boxes_iter = boxes.detach().cpu()
            else:
                boxes_iter = boxes

            xyxy = np.asarray(
                [[b[0] * w, b[1] * h, b[2] * w, b[3] * h] for box in boxes_iter for b in [box_cxcywh_to_xyxy(box)]],
                dtype=np.float32,
            )
            detections = sv.Detections(xyxy=xyxy, class_id=class_ids)
            labels = [str(c) for c in class_ids]
            scene = box_annotator.annotate(scene=scene, detections=detections)
            scene = label_annotator.annotate(scene=scene, detections=detections, labels=labels)

        ax.imshow(scene)
        ax.axis("off")


