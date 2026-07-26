"""YOLO 主线共用几何和坐标变换工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch


@dataclass(frozen=True)
class YoloLetterboxTransform:
    """记录一次 YOLO LetterBox 输入变换，便于预测框稳定反算回原图。"""

    source_width: int
    source_height: int
    target_width: int
    target_height: int
    gain: float
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    resized_width: int
    resized_height: int
    scaleup: bool
    centered: bool

    @property
    def source_size(self) -> tuple[int, int]:
        """返回原图尺寸，格式为 height, width。"""

        return (self.source_height, self.source_width)

    @property
    def target_size(self) -> tuple[int, int]:
        """返回模型输入尺寸，格式为 height, width。"""

        return (self.target_height, self.target_width)


def build_yolo_letterbox_transform(
    *,
    source_width: int,
    source_height: int,
    input_size: tuple[int, int],
    center: bool = True,
    scaleup: bool = True,
    auto: bool = False,
    stride: int = 32,
    scale_gain: float = 1.0,
) -> YoloLetterboxTransform:
    """按 Ultralytics LetterBox 规则计算缩放 gain 和四边 padding。

    ``input_size`` 明确使用 ``(height, width)``。validation 应传入
    ``scaleup=False``；训练和普通预测使用 ``scaleup=True``。``auto`` 只适合
    PyTorch 或支持动态空间 shape 的运行时，静态构建必须保持 ``False``。
    """

    target_height, target_width = int(input_size[0]), int(input_size[1])
    resolved_source_width = max(1, int(source_width))
    resolved_source_height = max(1, int(source_height))
    resolved_target_width = max(1, target_width)
    resolved_target_height = max(1, target_height)
    gain = min(
        float(resolved_target_height) / float(resolved_source_height),
        float(resolved_target_width) / float(resolved_source_width),
    )
    if not scaleup:
        gain = min(gain, 1.0)
    gain *= max(0.01, float(scale_gain))
    resized_width = max(1, int(round(float(resolved_source_width) * gain)))
    resized_height = max(1, int(round(float(resolved_source_height) * gain)))
    pad_width = resolved_target_width - resized_width
    pad_height = resolved_target_height - resized_height
    if auto:
        resolved_stride = max(1, int(stride))
        pad_width %= resolved_stride
        pad_height %= resolved_stride
        resolved_target_width = resized_width + pad_width
        resolved_target_height = resized_height + pad_height
    if center:
        pad_left = int(round(float(pad_width) / 2.0 - 0.1))
        pad_right = int(round(float(pad_width) / 2.0 + 0.1))
        pad_top = int(round(float(pad_height) / 2.0 - 0.1))
        pad_bottom = int(round(float(pad_height) / 2.0 + 0.1))
    else:
        pad_left = 0
        pad_top = 0
        pad_right = int(pad_width)
        pad_bottom = int(pad_height)
    return YoloLetterboxTransform(
        source_width=resolved_source_width,
        source_height=resolved_source_height,
        target_width=resolved_target_width,
        target_height=resolved_target_height,
        gain=float(gain),
        pad_left=pad_left,
        pad_top=pad_top,
        pad_right=pad_right,
        pad_bottom=pad_bottom,
        resized_width=resized_width,
        resized_height=resized_height,
        scaleup=bool(scaleup),
        centered=bool(center),
    )


def letterbox_yolo_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
    fill_value: int = 114,
    center: bool = True,
    scaleup: bool = True,
    auto: bool = False,
    stride: int = 32,
    scale_gain: float = 1.0,
) -> tuple[Any, YoloLetterboxTransform]:
    """把 BGR 图片按 YOLO LetterBox 规则缩放并填充到模型输入尺寸。"""

    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    transform = build_yolo_letterbox_transform(
        source_width=source_width,
        source_height=source_height,
        input_size=input_size,
        center=center,
        scaleup=scaleup,
        auto=auto,
        stride=stride,
        scale_gain=scale_gain,
    )
    if (
        transform.resized_width == source_width
        and transform.resized_height == source_height
    ):
        resized_image = image
    else:
        resized_image = cv2_module.resize(
            image,
            (transform.resized_width, transform.resized_height),
            interpolation=cv2_module.INTER_LINEAR,
        )
    canvas = np_module.full(
        (transform.target_height, transform.target_width, 3),
        int(fill_value),
        dtype=np_module.uint8,
    )
    source_x = max(0, -transform.pad_left)
    source_y = max(0, -transform.pad_top)
    target_x = max(0, transform.pad_left)
    target_y = max(0, transform.pad_top)
    copy_width = max(
        0,
        min(
            transform.resized_width - source_x,
            transform.target_width - target_x,
        ),
    )
    copy_height = max(
        0,
        min(
            transform.resized_height - source_y,
            transform.target_height - target_y,
        ),
    )
    if copy_height > 0 and copy_width > 0:
        canvas[
            target_y : target_y + copy_height,
            target_x : target_x + copy_width,
        ] = resized_image[
            source_y : source_y + copy_height,
            source_x : source_x + copy_width,
        ]
    return canvas, transform


def letterbox_yolo_image_to_canvas(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
    scale_gain: float = 1.0,
    scaleup: bool = True,
) -> tuple[Any, float, tuple[int, int]]:
    """生成 LetterBox 画布和可直接变换标注的 gain/pad 参数。"""

    canvas, transform = letterbox_yolo_image(
        cv2_module=cv2_module,
        np_module=np_module,
        image=image,
        input_size=input_size,
        scaleup=scaleup,
        scale_gain=scale_gain,
    )
    return canvas, transform.gain, (transform.pad_left, transform.pad_top)


def clip_yolo_xyxy_box(
    *,
    box_xyxy: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float] | None:
    """把 xyxy bbox 裁剪到指定图像范围。"""

    width = float(max(1, int(image_width)))
    height = float(max(1, int(image_height)))
    x1 = max(0.0, min(float(box_xyxy[0]), width))
    y1 = max(0.0, min(float(box_xyxy[1]), height))
    x2 = max(0.0, min(float(box_xyxy[2]), width))
    y2 = max(0.0, min(float(box_xyxy[3]), height))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def scale_yolo_box_to_letterbox(
    *,
    box_xyxy: tuple[float, float, float, float],
    transform: YoloLetterboxTransform,
) -> tuple[float, float, float, float] | None:
    """把原图 xyxy bbox 映射到 LetterBox 输入坐标。"""

    mapped_box = (
        float(box_xyxy[0]) * transform.gain + float(transform.pad_left),
        float(box_xyxy[1]) * transform.gain + float(transform.pad_top),
        float(box_xyxy[2]) * transform.gain + float(transform.pad_left),
        float(box_xyxy[3]) * transform.gain + float(transform.pad_top),
    )
    return clip_yolo_xyxy_box(
        box_xyxy=mapped_box,
        image_width=transform.target_width,
        image_height=transform.target_height,
    )


def scale_yolo_box_from_letterbox(
    *,
    box_xyxy: tuple[float, float, float, float],
    transform: YoloLetterboxTransform,
) -> tuple[float, float, float, float] | None:
    """把 LetterBox 输入坐标中的 xyxy bbox 反算回原图坐标。"""

    if transform.gain <= 0:
        return None
    mapped_box = (
        (float(box_xyxy[0]) - float(transform.pad_left)) / transform.gain,
        (float(box_xyxy[1]) - float(transform.pad_top)) / transform.gain,
        (float(box_xyxy[2]) - float(transform.pad_left)) / transform.gain,
        (float(box_xyxy[3]) - float(transform.pad_top)) / transform.gain,
    )
    return clip_yolo_xyxy_box(
        box_xyxy=mapped_box,
        image_width=transform.source_width,
        image_height=transform.source_height,
    )


def scale_yolo_point_from_letterbox(
    *,
    point_xy: tuple[float, float],
    transform: YoloLetterboxTransform,
) -> tuple[float, float]:
    """把 LetterBox 输入坐标中的点反算回原图坐标。"""

    if transform.gain <= 0:
        return (0.0, 0.0)
    x_value = (float(point_xy[0]) - float(transform.pad_left)) / transform.gain
    y_value = (float(point_xy[1]) - float(transform.pad_top)) / transform.gain
    x_value = max(0.0, min(x_value, float(transform.source_width)))
    y_value = max(0.0, min(y_value, float(transform.source_height)))
    return (x_value, y_value)


def scale_yolo_xywh_from_letterbox(
    *,
    box_xywh: tuple[float, float, float, float],
    transform: YoloLetterboxTransform,
) -> tuple[float, float, float, float] | None:
    """把 LetterBox 输入坐标中的 xywh bbox 反算回原图坐标。"""

    if transform.gain <= 0:
        return None
    center_x, center_y = scale_yolo_point_from_letterbox(
        point_xy=(float(box_xywh[0]), float(box_xywh[1])),
        transform=transform,
    )
    width = max(0.0, float(box_xywh[2]) / transform.gain)
    height = max(0.0, float(box_xywh[3]) / transform.gain)
    width = min(width, float(transform.source_width))
    height = min(height, float(transform.source_height))
    if width <= 0.0 or height <= 0.0:
        return None
    return (center_x, center_y, width, height)


def build_yolo_center_canvas_matrix(
    *,
    np_module: Any,
    image_shape: tuple[int, ...],
    output_size: tuple[int, int],
) -> Any:
    """构造只把大画布中心裁回目标尺寸的 3x3 affine 矩阵。

    ``output_size`` 使用 ``(width, height)``。该矩阵用于 Mosaic 后没有启用
    随机透视/仿射时的必需裁剪，不引入额外旋转、缩放或平移扰动。
    """

    source_height, source_width = int(image_shape[0]), int(image_shape[1])
    output_width, output_height = int(output_size[0]), int(output_size[1])
    center_matrix = np_module.eye(3, dtype=np_module.float32)
    center_matrix[0, 2] = -float(source_width) / 2.0
    center_matrix[1, 2] = -float(source_height) / 2.0
    translate_matrix = np_module.eye(3, dtype=np_module.float32)
    translate_matrix[0, 2] = float(output_width) / 2.0
    translate_matrix[1, 2] = float(output_height) / 2.0
    return translate_matrix @ center_matrix


def make_anchors(
    *,
    feature_maps: tuple[torch.Tensor, ...] | list[torch.Tensor],
    strides: tuple[int, ...],
) -> tuple[torch.Tensor, torch.Tensor]:
    """根据特征图尺寸生成 anchor points 与 stride 张量。"""

    anchor_points: list[torch.Tensor] = []
    stride_values: list[torch.Tensor] = []
    for feature_map, stride in zip(feature_maps, strides, strict=True):
        _, _, height, width = feature_map.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(height, device=feature_map.device, dtype=feature_map.dtype),
            torch.arange(width, device=feature_map.device, dtype=feature_map.dtype),
            indexing="ij",
        )
        points = torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) + 0.5
        anchor_points.append(points)
        stride_values.append(
            torch.full(
                (height * width, 1),
                float(stride),
                device=feature_map.device,
                dtype=feature_map.dtype,
            )
        )
    return torch.cat(anchor_points, dim=0), torch.cat(stride_values, dim=0)


def dist2bbox_xyxy(
    *,
    distances: torch.Tensor,
    anchor_points: torch.Tensor,
    stride_tensor: torch.Tensor,
) -> torch.Tensor:
    """把 left/top/right/bottom 距离解码成 xyxy 边界框。"""

    left_top, right_bottom = distances.chunk(2, dim=1)
    x1y1 = anchor_points.transpose(1, 2) - left_top
    x2y2 = anchor_points.transpose(1, 2) + right_bottom
    return torch.cat((x1y1, x2y2), dim=1) * stride_tensor.transpose(1, 2)


def dist2bbox_xywh(
    *,
    distances: torch.Tensor,
    anchor_points: torch.Tensor,
    stride_tensor: torch.Tensor,
) -> torch.Tensor:
    """把 left/top/right/bottom 距离解码成 Ultralytics 默认的 xywh 边界框。"""

    left_top, right_bottom = distances.chunk(2, dim=1)
    x1y1 = anchor_points.transpose(1, 2) - left_top
    x2y2 = anchor_points.transpose(1, 2) + right_bottom
    center_xy = (x1y1 + x2y2) / 2
    width_height = x2y2 - x1y1
    return torch.cat((center_xy, width_height), dim=1) * stride_tensor.transpose(1, 2)


def dist2rbox(
    pred_dist: torch.Tensor,
    pred_angle: torch.Tensor,
    anchor_points: torch.Tensor,
    dim: int = 1,
) -> torch.Tensor:
    """把距离分布、角度和 anchor points 解码成 xywhr 旋转框。"""

    left_top, right_bottom = pred_dist.split(2, dim=dim)
    cos_angle = torch.cos(pred_angle)
    sin_angle = torch.sin(pred_angle)
    # Ultralytics 的旋转框中心偏移是两侧距离差的一半。这里不能复用
    # axis-aligned box 的边角坐标语义，否则中心会沿旋转轴偏移一倍。
    xf, yf = ((right_bottom - left_top) / 2).chunk(2, dim=dim)
    x = xf * cos_angle - yf * sin_angle
    y = xf * sin_angle + yf * cos_angle
    xy = torch.cat([x, y], dim=dim)
    if anchor_points.ndim == 2:
        xy = xy + anchor_points.unsqueeze(0).permute(0, 2, 1)
    else:
        xy = xy + anchor_points
    return torch.cat([xy, left_top + right_bottom], dim=dim)
