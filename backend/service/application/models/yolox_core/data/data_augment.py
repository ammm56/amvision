"""项目内 YOLOX 数据增强与训练预处理。"""

from __future__ import annotations

import random

import cv2
import numpy as np

from ..utils import xyxy2cxcywh


def augment_hsv(img: np.ndarray, hgain: int = 5, sgain: int = 30, vgain: int = 30) -> None:
    """按 YOLOX 训练规则对输入图像执行 HSV 扰动。

    参数：
    - img：待增强的 BGR 图像。
    - hgain：Hue 扰动范围。
    - sgain：Saturation 扰动范围。
    - vgain：Value 扰动范围。
    """

    hsv_augs = np.random.uniform(-1, 1, 3) * [hgain, sgain, vgain]
    hsv_augs *= np.random.randint(0, 2, 3)
    hsv_augs = hsv_augs.astype(np.int16)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int16)

    img_hsv[..., 0] = (img_hsv[..., 0] + hsv_augs[0]) % 180
    img_hsv[..., 1] = np.clip(img_hsv[..., 1] + hsv_augs[1], 0, 255)
    img_hsv[..., 2] = np.clip(img_hsv[..., 2] + hsv_augs[2], 0, 255)
    cv2.cvtColor(img_hsv.astype(img.dtype), cv2.COLOR_HSV2BGR, dst=img)


def get_aug_params(value: float | tuple[float, float], center: float = 0.0) -> float:
    """按 YOLOX 规则生成单个增强参数。"""

    if isinstance(value, float | int):
        return random.uniform(center - float(value), center + float(value))
    if len(value) == 2:
        return random.uniform(float(value[0]), float(value[1]))
    raise ValueError(f"仿射增强参数必须是单个数值或长度为 2 的区间，当前收到 {value!r}")


def get_affine_matrix(
    target_size: tuple[int, int],
    degrees: float = 10.0,
    translate: float = 0.1,
    scales: float | tuple[float, float] = 0.1,
    shear: float = 10.0,
) -> tuple[np.ndarray, float]:
    """构建 YOLOX 随机仿射增强矩阵。"""

    target_width, target_height = target_size
    angle = get_aug_params(degrees)
    scale = get_aug_params(scales, center=1.0)
    if scale <= 0.0:
        raise ValueError("仿射增强的 scale 必须大于 0")

    rotation_matrix = cv2.getRotationMatrix2D(angle=angle, center=(0, 0), scale=scale)
    affine_matrix = np.ones((2, 3), dtype=np.float32)
    shear_x = np.tan(get_aug_params(shear) * np.pi / 180.0)
    shear_y = np.tan(get_aug_params(shear) * np.pi / 180.0)

    affine_matrix[0] = rotation_matrix[0] + shear_y * rotation_matrix[1]
    affine_matrix[1] = rotation_matrix[1] + shear_x * rotation_matrix[0]
    affine_matrix[0, 2] = get_aug_params(translate) * target_width
    affine_matrix[1, 2] = get_aug_params(translate) * target_height
    return affine_matrix, scale


def apply_affine_to_bboxes(
    targets: np.ndarray,
    target_size: tuple[int, int],
    affine_matrix: np.ndarray,
    _scale: float,
) -> np.ndarray:
    """把随机仿射矩阵同步应用到边界框坐标。"""

    num_ground_truths = len(targets)
    target_width, target_height = target_size
    corner_points = np.ones((4 * num_ground_truths, 3), dtype=np.float32)
    corner_points[:, :2] = targets[:, [0, 1, 2, 3, 0, 3, 2, 1]].reshape(4 * num_ground_truths, 2)
    corner_points = corner_points @ affine_matrix.T
    corner_points = corner_points.reshape(num_ground_truths, 8)

    corner_xs = corner_points[:, 0::2]
    corner_ys = corner_points[:, 1::2]
    new_bboxes = (
        np.concatenate(
            (
                corner_xs.min(axis=1),
                corner_ys.min(axis=1),
                corner_xs.max(axis=1),
                corner_ys.max(axis=1),
            )
        )
        .reshape(4, num_ground_truths)
        .T
    )
    new_bboxes[:, 0::2] = new_bboxes[:, 0::2].clip(0, target_width)
    new_bboxes[:, 1::2] = new_bboxes[:, 1::2].clip(0, target_height)
    targets[:, :4] = new_bboxes
    return targets


def random_affine(
    img: np.ndarray,
    targets: np.ndarray | tuple[()] = (),
    target_size: tuple[int, int] = (640, 640),
    degrees: float = 10.0,
    translate: float = 0.1,
    scales: float | tuple[float, float] = 0.1,
    shear: float = 10.0,
) -> tuple[np.ndarray, np.ndarray | tuple[()]]:
    """对图像和边界框执行 YOLOX 风格的随机仿射增强。"""

    affine_matrix, scale = get_affine_matrix(target_size, degrees, translate, scales, shear)
    transformed_image = cv2.warpAffine(
        img,
        affine_matrix,
        dsize=target_size,
        borderValue=(114, 114, 114),
    )
    if len(targets) > 0:
        targets = apply_affine_to_bboxes(targets, target_size, affine_matrix, scale)
    return transformed_image, targets


def adjust_box_anns(
    bbox: np.ndarray,
    scale_ratio: float,
    padw: float,
    padh: float,
    width: int,
    height: int,
) -> np.ndarray:
    """按缩放和平移结果同步修正边界框并裁剪到图像范围。"""

    bbox[:, 0::2] = np.clip(bbox[:, 0::2] * scale_ratio + padw, 0, width)
    bbox[:, 1::2] = np.clip(bbox[:, 1::2] * scale_ratio + padh, 0, height)
    return bbox


def _mirror(image: np.ndarray, boxes: np.ndarray, prob: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """按给定概率执行水平翻转，并同步更新框坐标。"""

    _, width, _ = image.shape
    if random.random() < prob:
        image = image[:, ::-1]
        boxes[:, 0::2] = width - boxes[:, 2::-2]
    return image, boxes


def preproc(
    img: np.ndarray,
    input_size: tuple[int, int],
    swap: tuple[int, int, int] = (2, 0, 1),
) -> tuple[np.ndarray, float]:
    """按 YOLOX 方式把图像缩放并 pad 到固定输入尺寸。"""

    if len(img.shape) == 3:
        padded_img = np.ones((input_size[0], input_size[1], 3), dtype=np.uint8) * 114
    else:
        padded_img = np.ones(input_size, dtype=np.uint8) * 114

    resize_ratio = min(input_size[0] / img.shape[0], input_size[1] / img.shape[1])
    resized_img = cv2.resize(
        img,
        (int(img.shape[1] * resize_ratio), int(img.shape[0] * resize_ratio)),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.uint8)
    padded_img[: int(img.shape[0] * resize_ratio), : int(img.shape[1] * resize_ratio)] = (
        resized_img
    )

    padded_img = padded_img.transpose(swap)
    padded_img = np.ascontiguousarray(padded_img, dtype=np.float32)
    return padded_img, resize_ratio


class TrainTransform:
    """实现 YOLOX 训练阶段的样本预处理。"""

    def __init__(self, max_labels: int = 50, flip_prob: float = 0.5, hsv_prob: float = 1.0) -> None:
        """初始化训练预处理器。

        参数：
        - max_labels：单张图片保留的最大标签数。
        - flip_prob：水平翻转概率。
        - hsv_prob：HSV 扰动概率。
        """

        self.max_labels = max_labels
        self.flip_prob = flip_prob
        self.hsv_prob = hsv_prob

    def __call__(
        self,
        image: np.ndarray,
        targets: np.ndarray,
        input_dim: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        """执行 YOLOX 训练样本预处理。"""

        boxes = targets[:, :4].copy()
        labels = targets[:, 4].copy()
        if len(boxes) == 0:
            empty_targets = np.zeros((self.max_labels, 5), dtype=np.float32)
            processed_image, _ = preproc(image, input_dim)
            return processed_image, empty_targets

        original_image = image.copy()
        original_targets = targets.copy()
        original_boxes = original_targets[:, :4]
        original_labels = original_targets[:, 4]
        original_boxes = xyxy2cxcywh(original_boxes)

        if random.random() < self.hsv_prob:
            augment_hsv(image)
        transformed_image, boxes = _mirror(image, boxes, self.flip_prob)
        transformed_image, resize_ratio = preproc(transformed_image, input_dim)
        boxes = xyxy2cxcywh(boxes)
        boxes *= resize_ratio

        valid_box_mask = np.minimum(boxes[:, 2], boxes[:, 3]) > 1
        filtered_boxes = boxes[valid_box_mask]
        filtered_labels = labels[valid_box_mask]
        if len(filtered_boxes) == 0:
            transformed_image, original_ratio = preproc(original_image, input_dim)
            filtered_boxes = original_boxes * original_ratio
            filtered_labels = original_labels

        filtered_labels = np.expand_dims(filtered_labels, 1)
        combined_targets = np.hstack((filtered_labels, filtered_boxes))
        padded_labels = np.zeros((self.max_labels, 5), dtype=np.float32)
        padded_labels[range(len(combined_targets))[: self.max_labels]] = combined_targets[
            : self.max_labels
        ]
        padded_labels = np.ascontiguousarray(padded_labels, dtype=np.float32)
        return transformed_image, padded_labels


class ValTransform:
    """实现 YOLOX 验证和推理阶段的输入预处理。"""

    def __init__(
        self,
        swap: tuple[int, int, int] = (2, 0, 1),
        legacy: bool = False,
    ) -> None:
        """初始化验证预处理器。

        参数：
        - swap：输出张量通道顺序。
        - legacy：是否启用早期 YOLOX demo 使用的 RGB mean/std 归一化。
        """

        self.swap = swap
        self.legacy = legacy

    def __call__(
        self,
        image: np.ndarray,
        _target: object,
        input_size: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        """执行验证/推理图像预处理。

        返回：
        - np.ndarray：处理后的 CHW float32 图像。
        - np.ndarray：当前验证阶段不修改标签，返回占位数组保持 YOLOX 调用签名一致。
        """

        processed_image, _ = preproc(image, input_size, self.swap)
        if self.legacy:
            processed_image = processed_image[::-1, :, :].copy()
            processed_image /= 255.0
            processed_image -= np.array([0.485, 0.456, 0.406]).reshape(3, 1, 1)
            processed_image /= np.array([0.229, 0.224, 0.225]).reshape(3, 1, 1)
        return processed_image, np.zeros((1, 5), dtype=np.float32)
