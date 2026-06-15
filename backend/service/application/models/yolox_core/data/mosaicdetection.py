"""项目内 YOLOX MosaicDetection 包装器。"""

from __future__ import annotations

import random

import cv2
import numpy as np

from .data_augment import adjust_box_anns, random_affine


def get_mosaic_coordinate(
    mosaic_image: np.ndarray,
    mosaic_index: int,
    xc: int,
    yc: int,
    width: int,
    height: int,
    input_h: int,
    input_w: int,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """按 YOLOX 规则计算 Mosaic 子图在大画布中的落点。"""

    del mosaic_image
    if mosaic_index == 0:
        x1, y1, x2, y2 = max(xc - width, 0), max(yc - height, 0), xc, yc
        small_coord = width - (x2 - x1), height - (y2 - y1), width, height
    elif mosaic_index == 1:
        x1, y1, x2, y2 = xc, max(yc - height, 0), min(xc + width, input_w * 2), yc
        small_coord = 0, height - (y2 - y1), min(width, x2 - x1), height
    elif mosaic_index == 2:
        x1, y1, x2, y2 = max(xc - width, 0), yc, xc, min(input_h * 2, yc + height)
        small_coord = width - (x2 - x1), 0, width, min(y2 - y1, height)
    else:
        x1, y1, x2, y2 = xc, yc, min(xc + width, input_w * 2), min(input_h * 2, yc + height)
        small_coord = 0, 0, min(width, x2 - x1), min(y2 - y1, height)
    return (x1, y1, x2, y2), small_coord


class MosaicDetection:
    """对基础检测数据集附加 Mosaic 和 MixUp 增强。"""

    def __init__(
        self,
        *,
        dataset,
        img_size: tuple[int, int],
        mosaic: bool = True,
        preproc=None,
        degrees: float = 10.0,
        translate: float = 0.1,
        mosaic_scale: tuple[float, float] = (0.5, 1.5),
        mixup_scale: tuple[float, float] = (0.5, 1.5),
        shear: float = 2.0,
        enable_mixup: bool = True,
        mosaic_prob: float = 1.0,
        mixup_prob: float = 1.0,
    ) -> None:
        """初始化 MosaicDetection 包装器。"""

        self._dataset = dataset
        self.preproc = preproc
        self.degrees = degrees
        self.translate = translate
        self.scale = mosaic_scale
        self.shear = shear
        self.mixup_scale = mixup_scale
        self.enable_mosaic = mosaic
        self.enable_mixup = enable_mixup
        self.mosaic_prob = mosaic_prob
        self.mixup_prob = mixup_prob
        self._input_dim = tuple(img_size[:2])

    @property
    def input_dim(self) -> tuple[int, int]:
        """返回当前训练批次的输入尺寸。"""

        return tuple(self._input_dim)

    def set_input_dim(self, input_dim: tuple[int, int]) -> None:
        """更新当前训练批次的输入尺寸。"""

        self._input_dim = tuple(input_dim)
        if hasattr(self._dataset, "set_input_dim"):
            self._dataset.set_input_dim(tuple(input_dim))

    def close_mosaic(self) -> None:
        """关闭后续批次的 Mosaic 增强。"""

        self.enable_mosaic = False

    def __len__(self) -> int:
        """返回底层数据集大小。"""

        return len(self._dataset)

    def load_anno(self, index: int) -> np.ndarray:
        """透传读取底层样本标注。"""

        return self._dataset.load_anno(index)

    def pull_item(self, index: int):
        """透传读取底层原始样本。"""

        return self._dataset.pull_item(index)

    def __getitem__(self, index):
        """按当前配置返回普通样本或 Mosaic/MixUp 样本。"""

        if not isinstance(index, int):
            self.enable_mosaic = bool(index[0])
            if len(index) > 2 and index[2] is not None:
                self.set_input_dim(tuple(index[2]))
            index = int(index[1])
        if not isinstance(index, int):
            raise TypeError("MosaicDetection 期望收到整数索引或采样器元组")

        return self._getitem_impl(index)

    def _getitem_impl(self, index: int):
        """执行实际取样逻辑。"""

        if self.enable_mosaic and random.random() < self.mosaic_prob:
            return self._get_mosaic_item(index)

        image, labels, image_info, image_id = self._dataset.pull_item(index)
        transformed_image, transformed_labels = self.preproc(image, labels, self.input_dim)
        return transformed_image, transformed_labels, image_info, image_id

    def _get_mosaic_item(self, index: int):
        """构建单个 Mosaic/MixUp 训练样本。"""

        mosaic_labels: list[np.ndarray] = []
        input_h, input_w = self.input_dim
        yc = int(random.uniform(0.5 * input_h, 1.5 * input_h))
        xc = int(random.uniform(0.5 * input_w, 1.5 * input_w))
        indices = [index] + [random.randint(0, len(self._dataset) - 1) for _ in range(3)]
        image_id = -1

        for mosaic_index, sample_index in enumerate(indices):
            img, labels, _img_info, image_id = self._dataset.pull_item(sample_index)
            height0, width0 = img.shape[:2]
            scale = min(1.0 * input_h / height0, 1.0 * input_w / width0)
            resized_image = cv2.resize(
                img,
                (int(width0 * scale), int(height0 * scale)),
                interpolation=cv2.INTER_LINEAR,
            )
            height, width, channels = resized_image.shape[:3]
            if mosaic_index == 0:
                mosaic_image = np.full((input_h * 2, input_w * 2, channels), 114, dtype=np.uint8)

            large_coord, small_coord = get_mosaic_coordinate(
                mosaic_image,
                mosaic_index,
                xc,
                yc,
                width,
                height,
                input_h,
                input_w,
            )
            large_x1, large_y1, large_x2, large_y2 = large_coord
            small_x1, small_y1, small_x2, small_y2 = small_coord
            mosaic_image[large_y1:large_y2, large_x1:large_x2] = resized_image[
                small_y1:small_y2,
                small_x1:small_x2,
            ]
            padw, padh = large_x1 - small_x1, large_y1 - small_y1

            current_labels = labels.copy()
            if current_labels.size > 0:
                current_labels[:, 0] = scale * current_labels[:, 0] + padw
                current_labels[:, 1] = scale * current_labels[:, 1] + padh
                current_labels[:, 2] = scale * current_labels[:, 2] + padw
                current_labels[:, 3] = scale * current_labels[:, 3] + padh
            mosaic_labels.append(current_labels)

        if mosaic_labels:
            merged_labels = np.concatenate(mosaic_labels, axis=0)
            np.clip(merged_labels[:, 0], 0, 2 * input_w, out=merged_labels[:, 0])
            np.clip(merged_labels[:, 1], 0, 2 * input_h, out=merged_labels[:, 1])
            np.clip(merged_labels[:, 2], 0, 2 * input_w, out=merged_labels[:, 2])
            np.clip(merged_labels[:, 3], 0, 2 * input_h, out=merged_labels[:, 3])
        else:
            merged_labels = np.zeros((0, 5), dtype=np.float32)

        mosaic_image, merged_labels = random_affine(
            mosaic_image,
            merged_labels,
            target_size=(input_w, input_h),
            degrees=self.degrees,
            translate=self.translate,
            scales=self.scale,
            shear=self.shear,
        )
        if (
            self.enable_mixup
            and len(merged_labels) > 0
            and random.random() < self.mixup_prob
        ):
            mosaic_image, merged_labels = self.mixup(mosaic_image, merged_labels, self.input_dim)

        processed_image, padded_labels = self.preproc(mosaic_image, merged_labels, self.input_dim)
        image_info = (processed_image.shape[1], processed_image.shape[0])
        return processed_image, padded_labels, image_info, image_id

    def mixup(
        self,
        origin_img: np.ndarray,
        origin_labels: np.ndarray,
        input_dim: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        """按 YOLOX 规则执行 MixUp。"""

        jit_factor = random.uniform(*self.mixup_scale)
        should_flip = random.uniform(0, 1) > 0.5
        copied_labels = np.zeros((0, 5), dtype=np.float32)
        while len(copied_labels) == 0:
            copied_index = random.randint(0, len(self._dataset) - 1)
            copied_labels = self._dataset.load_anno(copied_index)
        copied_image, copied_labels, _img_info, _img_id = self._dataset.pull_item(copied_index)

        if len(copied_image.shape) == 3:
            copied_canvas = np.ones((input_dim[0], input_dim[1], 3), dtype=np.uint8) * 114
        else:
            copied_canvas = np.ones(input_dim, dtype=np.uint8) * 114

        copied_scale_ratio = min(
            input_dim[0] / copied_image.shape[0],
            input_dim[1] / copied_image.shape[1],
        )
        resized_image = cv2.resize(
            copied_image,
            (
                int(copied_image.shape[1] * copied_scale_ratio),
                int(copied_image.shape[0] * copied_scale_ratio),
            ),
            interpolation=cv2.INTER_LINEAR,
        )
        copied_canvas[
            : int(copied_image.shape[0] * copied_scale_ratio),
            : int(copied_image.shape[1] * copied_scale_ratio),
        ] = resized_image

        copied_canvas = cv2.resize(
            copied_canvas,
            (
                int(copied_canvas.shape[1] * jit_factor),
                int(copied_canvas.shape[0] * jit_factor),
            ),
        )
        copied_scale_ratio *= jit_factor
        if should_flip:
            copied_canvas = copied_canvas[:, ::-1, :]

        origin_h, origin_w = copied_canvas.shape[:2]
        target_h, target_w = origin_img.shape[:2]
        padded_image = np.zeros(
            (max(origin_h, target_h), max(origin_w, target_w), 3),
            dtype=np.uint8,
        )
        padded_image[:origin_h, :origin_w] = copied_canvas

        x_offset = 0
        y_offset = 0
        if padded_image.shape[0] > target_h:
            y_offset = random.randint(0, padded_image.shape[0] - target_h - 1)
        if padded_image.shape[1] > target_w:
            x_offset = random.randint(0, padded_image.shape[1] - target_w - 1)
        padded_cropped_img = padded_image[
            y_offset:y_offset + target_h,
            x_offset:x_offset + target_w,
        ]

        copied_bboxes = adjust_box_anns(
            copied_labels[:, :4].copy(),
            copied_scale_ratio,
            0,
            0,
            origin_w,
            origin_h,
        )
        if should_flip:
            copied_bboxes[:, 0::2] = origin_w - copied_bboxes[:, 0::2][:, ::-1]
        transformed_bboxes = copied_bboxes.copy()
        transformed_bboxes[:, 0::2] = np.clip(
            transformed_bboxes[:, 0::2] - x_offset,
            0,
            target_w,
        )
        transformed_bboxes[:, 1::2] = np.clip(
            transformed_bboxes[:, 1::2] - y_offset,
            0,
            target_h,
        )

        cls_labels = copied_labels[:, 4:5].copy()
        labels = np.hstack((transformed_bboxes, cls_labels))
        merged_labels = np.vstack((origin_labels, labels))
        mixed_image = origin_img.astype(np.float32) * 0.5 + padded_cropped_img.astype(np.float32) * 0.5
        return mixed_image.astype(np.uint8), merged_labels