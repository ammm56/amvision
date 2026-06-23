"""RF-DETR core 核心处理模块：`supervision_compat`。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Color:
    """RF-DETR core 类：`Color`。"""

    r: int
    g: int
    b: int
    a: int = 255

    def as_rgb(self) -> tuple[int, int, int]:
        """执行 `as_rgb`。
        
        返回：
        - 当前函数的执行结果。
        """
        return self.r, self.g, self.b

    def as_bgr(self) -> tuple[int, int, int]:
        """执行 `as_bgr`。
        
        返回：
        - 当前函数的执行结果。
        """
        return self.b, self.g, self.r


Color.BLACK = Color(0, 0, 0)  # type: ignore[attr-defined]
Color.WHITE = Color(255, 255, 255)  # type: ignore[attr-defined]
Color.RED = Color(255, 0, 0)  # type: ignore[attr-defined]
Color.GREEN = Color(0, 255, 0)  # type: ignore[attr-defined]
Color.BLUE = Color(0, 0, 255)  # type: ignore[attr-defined]
Color.ROBOFLOW = Color(163, 81, 251)  # type: ignore[attr-defined]


class ColorLookup(Enum):
    """RF-DETR core 类：`ColorLookup`。"""

    CLASS = "class"


class Position(Enum):
    """文字绘制位置。"""

    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"


@dataclass(frozen=True)
class ColorPalette:
    """RF-DETR core 类：`ColorPalette`。"""

    colors: list[Color]

    def by_idx(self, idx: int) -> Color:
        """根据索引返回颜色，索引越界时循环取色。"""
        if not self.colors:
            return Color.ROBOFLOW  # type: ignore[attr-defined]
        return self.colors[idx % len(self.colors)]


@dataclass
class Detections:
    """RF-DETR core 类：`Detections`。"""

    xyxy: np.ndarray
    mask: np.ndarray | None = None
    confidence: np.ndarray | None = None
    class_id: np.ndarray | None = None
    tracker_id: np.ndarray | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """规范化数组形状，保证空结果也能稳定处理。"""
        self.xyxy = np.asarray(self.xyxy, dtype=np.float32).reshape(-1, 4)
        if self.class_id is not None:
            self.class_id = np.asarray(self.class_id, dtype=np.int64).reshape(-1)
        if self.confidence is not None:
            self.confidence = np.asarray(self.confidence, dtype=np.float32).reshape(-1)
        if self.mask is not None:
            self.mask = np.asarray(self.mask, dtype=bool)

    def __len__(self) -> int:
        """返回目标数量。"""
        return int(self.xyxy.shape[0])

    @classmethod
    def empty(cls) -> Detections:
        """创建空检测结果。"""
        return cls(xyxy=np.zeros((0, 4), dtype=np.float32), class_id=np.zeros((0,), dtype=np.int64))


def xywh_to_xyxy(xywh: np.ndarray) -> np.ndarray:
    """执行 `xywh_to_xyxy`。
    
    参数：
    - `xywh`：传入的 `xywh` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    boxes = np.asarray(xywh, dtype=np.float32).reshape(-1, 4)
    result = boxes.copy()
    result[:, 2] = boxes[:, 0] + boxes[:, 2]
    result[:, 3] = boxes[:, 1] + boxes[:, 3]
    return result


def box_iou_batch(boxes_true: np.ndarray, boxes_detection: np.ndarray) -> np.ndarray:
    """执行 `box_iou_batch`。
    
    参数：
    - `boxes_true`：传入的 `boxes_true` 参数。
    - `boxes_detection`：传入的 `boxes_detection` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    true_boxes = np.asarray(boxes_true, dtype=np.float32).reshape(-1, 4)
    det_boxes = np.asarray(boxes_detection, dtype=np.float32).reshape(-1, 4)
    if true_boxes.size == 0 or det_boxes.size == 0:
        return np.zeros((len(true_boxes), len(det_boxes)), dtype=np.float32)

    true_area = np.maximum(0.0, true_boxes[:, 2] - true_boxes[:, 0]) * np.maximum(
        0.0, true_boxes[:, 3] - true_boxes[:, 1]
    )
    det_area = np.maximum(0.0, det_boxes[:, 2] - det_boxes[:, 0]) * np.maximum(
        0.0, det_boxes[:, 3] - det_boxes[:, 1]
    )

    lt = np.maximum(true_boxes[:, None, :2], det_boxes[None, :, :2])
    rb = np.minimum(true_boxes[:, None, 2:], det_boxes[None, :, 2:])
    wh = np.maximum(0.0, rb - lt)
    inter = wh[:, :, 0] * wh[:, :, 1]
    union = true_area[:, None] + det_area[None, :] - inter
    return np.divide(inter, np.maximum(union, 1e-9), dtype=np.float32)


def draw_filled_polygon(scene: np.ndarray, polygon: np.ndarray, color: Color) -> np.ndarray:
    """执行 `draw_filled_polygon`。
    
    参数：
    - `scene`：传入的 `scene` 参数。
    - `polygon`：传入的 `polygon` 参数。
    - `color`：传入的 `color` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    cv2.fillPoly(scene, [np.asarray(polygon, dtype=np.int32)], color.as_bgr())
    return scene


def _ensure_pil(scene: Image.Image | np.ndarray) -> tuple[Image.Image, bool]:
    """执行 `_ensure_pil`。
    
    参数：
    - `scene`：传入的 `scene` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if isinstance(scene, Image.Image):
        return scene, True
    return Image.fromarray(np.asarray(scene)), False


def _restore_scene(scene: Image.Image, was_pil: bool) -> Image.Image | np.ndarray:
    """按输入类型恢复绘图结果。"""
    if was_pil:
        return scene
    return np.asarray(scene)


class BoxAnnotator:
    """当前 RF-DETR core 使用的边界框绘制器。"""

    def __init__(
        self,
        color: ColorPalette | Color | None = None,
        thickness: int = 2,
        color_lookup: ColorLookup | None = None,
    ) -> None:
        self.color = color or Color.ROBOFLOW  # type: ignore[attr-defined]
        self.thickness = thickness
        self.color_lookup = color_lookup

    def _color_for(self, detections: Detections, index: int) -> Color:
        class_id = int(detections.class_id[index]) if detections.class_id is not None else index
        if isinstance(self.color, ColorPalette):
            return self.color.by_idx(class_id)
        return self.color

    def annotate(self, scene: Image.Image | np.ndarray, detections: Detections) -> Image.Image | np.ndarray:
        """在图像上绘制检测框。"""
        image, was_pil = _ensure_pil(scene)
        draw = ImageDraw.Draw(image)
        for i, box in enumerate(detections.xyxy):
            color = self._color_for(detections, i).as_rgb()
            xyxy = tuple(float(v) for v in box)
            for offset in range(self.thickness):
                draw.rectangle(
                    (xyxy[0] - offset, xyxy[1] - offset, xyxy[2] + offset, xyxy[3] + offset),
                    outline=color,
                )
        return _restore_scene(image, was_pil)


class LabelAnnotator:
    """当前 RF-DETR core 使用的文字标签绘制器。"""

    def __init__(
        self,
        color: ColorPalette | Color | None = None,
        text_color: Color | None = None,
        text_scale: float = 0.5,
        text_padding: int = 3,
        text_position: Position = Position.TOP_LEFT,
        color_lookup: ColorLookup | None = None,
    ) -> None:
        self.color = color or Color.ROBOFLOW  # type: ignore[attr-defined]
        self.text_color = text_color or Color.BLACK  # type: ignore[attr-defined]
        self.text_scale = text_scale
        self.text_padding = text_padding
        self.text_position = text_position
        self.color_lookup = color_lookup

    def _background_for(self, detections: Detections, index: int) -> Color:
        class_id = int(detections.class_id[index]) if detections.class_id is not None else index
        if isinstance(self.color, ColorPalette):
            return self.color.by_idx(class_id)
        return self.color

    def annotate(
        self,
        scene: Image.Image | np.ndarray,
        detections: Detections,
        labels: list[str],
    ) -> Image.Image | np.ndarray:
        """在图像上绘制标签文字。"""
        image, was_pil = _ensure_pil(scene)
        draw = ImageDraw.Draw(image)
        for i, label in enumerate(labels):
            if i >= len(detections):
                break
            x1, y1, x2, _ = (float(v) for v in detections.xyxy[i])
            text = str(label)
            text_bbox = draw.textbbox((0, 0), text)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            if self.text_position == Position.TOP_RIGHT:
                tx = max(0.0, x2 - text_w - 2 * self.text_padding)
            else:
                tx = x1
            ty = max(0.0, y1 - text_h - 2 * self.text_padding)
            bg = self._background_for(detections, i).as_rgb()
            draw.rectangle(
                (
                    tx,
                    ty,
                    tx + text_w + 2 * self.text_padding,
                    ty + text_h + 2 * self.text_padding,
                ),
                fill=bg,
            )
            draw.text(
                (tx + self.text_padding, ty + self.text_padding),
                text,
                fill=self.text_color.as_rgb(),
            )
        return _restore_scene(image, was_pil)
