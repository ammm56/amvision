"""OpenCV 搜索节点共用的结果上限与处理分辨率保护。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError


DEFAULT_FIND_RESULT_LIMIT = 10
MAX_FIND_RESULT_LIMIT = 1000
DEFAULT_PROCESSING_MAX_LONG_EDGE = 2048
MAX_PROCESSING_LONG_EDGE = 32768
UNBOUNDED_CIRCLE_SOURCE_PIXEL_LIMIT = 4_000_000


@dataclass(frozen=True)
class ProcessingImage:
    """保存算法处理图及其到 Search ROI 原坐标的缩放关系。"""

    image_matrix: Any
    source_width: int
    source_height: int
    processing_width: int
    processing_height: int
    scale_x_to_source: float
    scale_y_to_source: float
    resized: bool


def read_find_result_limit(
    raw_value: object,
    *,
    field_name: str = "limit",
    default: int = DEFAULT_FIND_RESULT_LIMIT,
    maximum: int = MAX_FIND_RESULT_LIMIT,
) -> int:
    """读取搜索结果上限；空值使用安全默认值，禁止无限结果。"""

    if maximum <= 0:
        raise ValueError("maximum 必须大于 0")
    if is_empty_parameter(raw_value):
        return min(default, maximum)
    if isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{field_name} 必须是正整数") from exc
    if value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    if value > maximum:
        raise InvalidRequestError(f"{field_name} 不能大于 {maximum}")
    return value


def read_processing_max_long_edge(
    raw_value: object,
    *,
    default: int = DEFAULT_PROCESSING_MAX_LONG_EDGE,
) -> int:
    """读取算法处理图最长边限制。"""

    if is_empty_parameter(raw_value):
        return default
    if isinstance(raw_value, bool):
        raise InvalidRequestError("processing_max_long_edge 必须是正整数")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("processing_max_long_edge 必须是正整数") from exc
    if value < 256:
        raise InvalidRequestError("processing_max_long_edge 不能小于 256")
    if value > MAX_PROCESSING_LONG_EDGE:
        raise InvalidRequestError(
            f"processing_max_long_edge 不能大于 {MAX_PROCESSING_LONG_EDGE}"
        )
    return value


def build_processing_image(
    image_matrix: Any,
    *,
    cv2_module: Any,
    max_long_edge: int,
) -> ProcessingImage:
    """按最长边限制缩小 Search ROI，并保留精确坐标还原比例。"""

    source_height, source_width = [int(value) for value in image_matrix.shape[:2]]
    if source_width <= 0 or source_height <= 0:
        raise InvalidRequestError("OpenCV 搜索区域尺寸无效")
    source_long_edge = max(source_width, source_height)
    if source_long_edge <= max_long_edge:
        return ProcessingImage(
            image_matrix=image_matrix,
            source_width=source_width,
            source_height=source_height,
            processing_width=source_width,
            processing_height=source_height,
            scale_x_to_source=1.0,
            scale_y_to_source=1.0,
            resized=False,
        )

    scale = float(max_long_edge) / float(source_long_edge)
    processing_width = max(1, int(round(source_width * scale)))
    processing_height = max(1, int(round(source_height * scale)))
    resized_matrix = cv2_module.resize(
        image_matrix,
        (processing_width, processing_height),
        interpolation=cv2_module.INTER_AREA,
    )
    return ProcessingImage(
        image_matrix=resized_matrix,
        source_width=source_width,
        source_height=source_height,
        processing_width=processing_width,
        processing_height=processing_height,
        scale_x_to_source=float(source_width) / float(processing_width),
        scale_y_to_source=float(source_height) / float(processing_height),
        resized=True,
    )


def build_processing_summary(processing_image: ProcessingImage) -> dict[str, object]:
    """构造可诊断的处理分辨率摘要。"""

    return {
        "processing_resized": processing_image.resized,
        "processing_width": processing_image.processing_width,
        "processing_height": processing_image.processing_height,
        "processing_scale_x_to_source": round(processing_image.scale_x_to_source, 8),
        "processing_scale_y_to_source": round(processing_image.scale_y_to_source, 8),
    }


def require_bounded_circle_search(
    *,
    source_width: int,
    source_height: int,
    min_radius: int,
    max_radius: int,
) -> None:
    """阻止高分辨率图片使用完全不受限的 Hough Circle 半径搜索。"""

    source_pixels = source_width * source_height
    if (
        source_pixels > UNBOUNDED_CIRCLE_SOURCE_PIXEL_LIMIT
        and min_radius == 0
        and max_radius == 0
    ):
        raise InvalidRequestError(
            "高分辨率 Hough Circles 必须设置 Search ROI 或 Min/Max Radius，"
            "不能在大图上执行完全不受限的半径搜索",
            details={
                "search_width": source_width,
                "search_height": source_height,
                "search_pixels": source_pixels,
                "pixel_limit": UNBOUNDED_CIRCLE_SOURCE_PIXEL_LIMIT,
            },
        )
