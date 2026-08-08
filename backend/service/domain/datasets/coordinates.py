"""数据集统一坐标语义和边界转换。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Final, Literal


CoordinateConvention = Literal[
    "zero-based-exclusive",
    "pascal-voc-1-based-inclusive",
]

ZERO_BASED_EXCLUSIVE: Final[CoordinateConvention] = "zero-based-exclusive"
PASCAL_VOC_ONE_BASED_INCLUSIVE: Final[CoordinateConvention] = (
    "pascal-voc-1-based-inclusive"
)
PIXEL_BOUNDARY_EPSILON: Final[float] = 1e-6
YOLO_NORMALIZED_BOUNDARY_EPSILON: Final[float] = 1e-6


@dataclass(frozen=True)
class PixelBox:
    """表示平台内部 0-based、右下边界 exclusive 的连续像素框。

    坐标范围固定为 ``[0, width] x [0, height]``。``x_max`` 和
    ``y_max`` 是 exclusive 边界，因此位于图片最右侧或最下侧的目标可以分别
    使用 ``width`` 和 ``height`` 作为边界值。
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @classmethod
    def from_external_xyxy(
        cls,
        *,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        convention: CoordinateConvention,
        image_width: int,
        image_height: int,
    ) -> PixelBox:
        """把明确坐标方言的外部 xyxy 转换为平台内部坐标。"""

        if convention == ZERO_BASED_EXCLUSIVE:
            box = cls(xmin, ymin, xmax, ymax)
        elif convention == PASCAL_VOC_ONE_BASED_INCLUSIVE:
            box = cls(xmin - 1.0, ymin - 1.0, xmax, ymax)
        else:  # pragma: no cover - Literal 之外的运行时防御
            raise ValueError(f"未知坐标约定: {convention}")
        box.validate(image_width=image_width, image_height=image_height)
        return box

    @classmethod
    def from_xywh(
        cls,
        bbox_xywh: tuple[float, float, float, float],
        *,
        image_width: int,
        image_height: int,
    ) -> PixelBox:
        """把平台存储的 0-based xywh 转换为内部边界框并校验。"""

        x, y, width, height = bbox_xywh
        box = cls._from_edges_with_boundary_tolerance(
            x_min=x,
            y_min=y,
            x_max=x + width,
            y_max=y + height,
            image_width=image_width,
            image_height=image_height,
        )
        box.validate(image_width=image_width, image_height=image_height)
        return box

    @classmethod
    def from_yolo_normalized_xywh(
        cls,
        bbox_xywh: tuple[float, float, float, float],
        *,
        image_width: int,
        image_height: int,
    ) -> PixelBox:
        """把 YOLO 归一化中心点框转换为规范像素边界。

        先在归一化坐标中计算四条边界，再吸收六位小数 YOLO 标签量化产生的
        最多百万分之一边界误差，最后缩放为像素坐标。超过量化精度的真实越界
        仍会被拒绝。
        """

        center_x, center_y, width, height = bbox_xywh
        normalized_x_min = _snap_lower_boundary(
            center_x - width / 2.0,
            epsilon=YOLO_NORMALIZED_BOUNDARY_EPSILON,
        )
        normalized_y_min = _snap_lower_boundary(
            center_y - height / 2.0,
            epsilon=YOLO_NORMALIZED_BOUNDARY_EPSILON,
        )
        normalized_x_max = _snap_upper_boundary(
            center_x + width / 2.0,
            upper=1.0,
            epsilon=YOLO_NORMALIZED_BOUNDARY_EPSILON,
        )
        normalized_y_max = _snap_upper_boundary(
            center_y + height / 2.0,
            upper=1.0,
            epsilon=YOLO_NORMALIZED_BOUNDARY_EPSILON,
        )
        box = cls(
            normalized_x_min * image_width,
            normalized_y_min * image_height,
            normalized_x_max * image_width,
            normalized_y_max * image_height,
        )
        box.validate(image_width=image_width, image_height=image_height)
        return box

    @classmethod
    def _from_edges_with_boundary_tolerance(
        cls,
        *,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        image_width: int,
        image_height: int,
    ) -> PixelBox:
        """仅把紧邻图片外边界的浮点运算残差吸收到精确边界。"""

        return cls(
            _snap_lower_boundary(float(x_min)),
            _snap_lower_boundary(float(y_min)),
            _snap_upper_boundary(float(x_max), upper=float(image_width)),
            _snap_upper_boundary(float(y_max), upper=float(image_height)),
        )

    def validate(self, *, image_width: int, image_height: int) -> None:
        """校验坐标有限、正面积并位于图片边界内。"""

        if image_width <= 0 or image_height <= 0:
            raise ValueError("图片宽高必须大于 0")
        values = (self.x_min, self.y_min, self.x_max, self.y_max)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bbox 坐标必须是有限数字")
        if not (0.0 <= self.x_min < self.x_max <= float(image_width)):
            raise ValueError("bbox x 坐标必须满足 0 <= xmin < xmax <= image_width")
        if not (0.0 <= self.y_min < self.y_max <= float(image_height)):
            raise ValueError("bbox y 坐标必须满足 0 <= ymin < ymax <= image_height")

    def to_xywh(self) -> tuple[float, float, float, float]:
        """返回平台统一的 0-based xywh。"""

        return (
            self.x_min,
            self.y_min,
            self.x_max - self.x_min,
            self.y_max - self.y_min,
        )

    def to_integer_xyxy(
        self,
        *,
        convention: CoordinateConvention,
        image_width: int,
        image_height: int,
    ) -> tuple[int, int, int, int]:
        """按外包围量化规则生成 VOC XML 使用的整数 xyxy。

        最小边界使用 ``floor``，最大 exclusive 边界使用 ``ceil``，保证从浮点
        标注导出时不会缩小目标。量化后再次校验图片边界。
        """

        self.validate(image_width=image_width, image_height=image_height)
        x_min = max(0, min(image_width - 1, math.floor(self.x_min)))
        y_min = max(0, min(image_height - 1, math.floor(self.y_min)))
        x_max = max(x_min + 1, min(image_width, math.ceil(self.x_max)))
        y_max = max(y_min + 1, min(image_height, math.ceil(self.y_max)))
        if convention == ZERO_BASED_EXCLUSIVE:
            return (x_min, y_min, x_max, y_max)
        if convention == PASCAL_VOC_ONE_BASED_INCLUSIVE:
            return (x_min + 1, y_min + 1, x_max, y_max)
        raise ValueError(f"未知坐标约定: {convention}")


def _snap_lower_boundary(
    value: float,
    *,
    epsilon: float = PIXEL_BOUNDARY_EPSILON,
) -> float:
    """把微小负零误差吸收到 0，不修改合法的正坐标。"""

    if -epsilon <= value < 0.0:
        return 0.0
    return value


def _snap_upper_boundary(
    value: float,
    *,
    upper: float,
    epsilon: float = PIXEL_BOUNDARY_EPSILON,
) -> float:
    """把微小上边界溢出吸收到精确 exclusive 边界。"""

    if upper < value <= upper + epsilon:
        return upper
    return value
