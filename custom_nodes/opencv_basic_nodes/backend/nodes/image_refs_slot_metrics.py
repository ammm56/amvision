"""Image refs 批量槽位指标公共工具。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
    require_uint8_int,
)


@dataclass(frozen=True)
class ImageRefsSlotMetricConfig:
    """描述批量槽位图片指标计算参数。"""

    max_items: int | None
    dark_threshold: int
    bright_threshold: int
    canny_low_threshold: int
    canny_high_threshold: int
    dark_morph_kernel_size: int
    dark_component_min_area: float | None


def read_slot_metric_config(
    request: WorkflowNodeExecutionRequest,
    *,
    node_display_name: str,
) -> ImageRefsSlotMetricConfig:
    """从节点参数读取通用槽位指标配置。

    参数：
    - request：当前节点执行请求。
    - node_display_name：错误消息中使用的节点名称。

    返回：
    - ImageRefsSlotMetricConfig：规范化后的指标配置。
    """

    canny_low_threshold = read_uint8_with_default(
        request.parameters.get("canny_low_threshold"),
        field_name="canny_low_threshold",
        default_value=50,
    )
    canny_high_threshold = read_uint8_with_default(
        request.parameters.get("canny_high_threshold"),
        field_name="canny_high_threshold",
        default_value=150,
    )
    if canny_high_threshold < canny_low_threshold:
        raise InvalidRequestError(f"{node_display_name} 节点的 canny_high_threshold 必须大于等于 canny_low_threshold")
    return ImageRefsSlotMetricConfig(
        max_items=read_optional_positive_int(request.parameters.get("max_items"), field_name="max_items"),
        dark_threshold=read_uint8_with_default(
            request.parameters.get("dark_threshold"),
            field_name="dark_threshold",
            default_value=64,
        ),
        bright_threshold=read_uint8_with_default(
            request.parameters.get("bright_threshold"),
            field_name="bright_threshold",
            default_value=192,
        ),
        canny_low_threshold=canny_low_threshold,
        canny_high_threshold=canny_high_threshold,
        dark_morph_kernel_size=read_odd_kernel_with_default(
            request.parameters.get("dark_morph_kernel_size"),
            field_name="dark_morph_kernel_size",
            default_value=3,
        ),
        dark_component_min_area=read_optional_non_negative_float(
            request.parameters.get("dark_component_min_area"),
            field_name="dark_component_min_area",
            default_value=20,
        ),
    )


def build_slot_metric_item(
    *,
    cv2_module: object,
    np_module: object,
    image_payload: dict[str, object],
    image_matrix: object,
    item_index: int,
    config: ImageRefsSlotMetricConfig,
    node_display_name: str,
) -> dict[str, object]:
    """计算单张槽位图片的灰度、边缘和暗连通域指标。

    参数：
    - cv2_module：OpenCV 模块。
    - np_module：NumPy 模块。
    - image_payload：当前 image-ref payload。
    - image_matrix：当前图片矩阵。
    - item_index：批量图片序号。
    - config：指标计算参数。
    - node_display_name：错误消息中使用的节点名称。

    返回：
    - dict[str, object]：包含尺寸、透传 ROI 信息和 metrics 的稳定 JSON 结构。
    """

    if len(image_matrix.shape) == 2:
        gray_image = image_matrix
    else:
        gray_image = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)
    pixel_count = int(gray_image.size)
    if pixel_count <= 0:
        raise InvalidRequestError(f"{node_display_name} 节点读取到空图片")

    edge_image = cv2_module.Canny(
        gray_image,
        config.canny_low_threshold,
        config.canny_high_threshold,
    )
    dark_mask = (gray_image <= config.dark_threshold).astype(np_module.uint8)
    if config.dark_morph_kernel_size > 1:
        kernel = cv2_module.getStructuringElement(
            cv2_module.MORPH_RECT,
            (config.dark_morph_kernel_size, config.dark_morph_kernel_size),
        )
        dark_mask = cv2_module.morphologyEx(dark_mask, cv2_module.MORPH_OPEN, kernel)

    metrics = {
        "mean_gray": float(np_module.mean(gray_image)),
        "std_gray": float(np_module.std(gray_image)),
        "min_gray": int(np_module.min(gray_image)),
        "max_gray": int(np_module.max(gray_image)),
        "dark_ratio": float(np_module.count_nonzero(gray_image <= config.dark_threshold) / pixel_count),
        "bright_ratio": float(np_module.count_nonzero(gray_image >= config.bright_threshold) / pixel_count),
        "edge_density": float(np_module.count_nonzero(edge_image) / pixel_count),
        **measure_dark_components(
            cv2_module=cv2_module,
            dark_mask=dark_mask,
            pixel_count=pixel_count,
            min_area=config.dark_component_min_area,
        ),
    }
    result = {
        "index": item_index,
        "width": int(image_payload.get("width") or image_matrix.shape[1]),
        "height": int(image_payload.get("height") or image_matrix.shape[0]),
        "pixel_count": pixel_count,
        "metrics": round_metrics(metrics),
    }
    for passthrough_key in ("crop_index", "roi_id", "roi_kind", "bbox_xyxy"):
        if passthrough_key in image_payload:
            result[passthrough_key] = image_payload[passthrough_key]
    return result


def measure_dark_components(
    *,
    cv2_module: object,
    dark_mask: object,
    pixel_count: int,
    min_area: float | None,
) -> dict[str, object]:
    """统计暗像素连通域。

    该函数只输出数值指标，不输出 mask 或 debug 图，避免批量槽位生产链路引入额外图片编码。
    """

    label_count, _labels, stats, _centroids = cv2_module.connectedComponentsWithStats(
        dark_mask,
        connectivity=8,
    )
    component_areas: list[int] = []
    for label_index in range(1, int(label_count)):
        area = int(stats[label_index, cv2_module.CC_STAT_AREA])
        if min_area is not None and float(area) < min_area:
            continue
        component_areas.append(area)
    total_area = int(sum(component_areas))
    largest_area = int(max(component_areas, default=0))
    return {
        "dark_component_count": len(component_areas),
        "dark_component_area_ratio": float(total_area / pixel_count),
        "largest_dark_component_area_ratio": float(largest_area / pixel_count),
    }


def build_max_check(value: object, threshold: float | None) -> dict[str, object]:
    """构建 value <= threshold 规则结果。"""

    if threshold is None:
        return {"enabled": False, "operator": "<=", "threshold": None, "value": round_float(value), "passed": None}
    numeric_value = float(value)
    return {
        "enabled": True,
        "operator": "<=",
        "threshold": round(float(threshold), 8),
        "value": round(numeric_value, 8),
        "passed": numeric_value <= float(threshold),
    }


def build_min_check(value: object, threshold: float | None) -> dict[str, object]:
    """构建 value >= threshold 规则结果。"""

    if threshold is None:
        return {"enabled": False, "operator": ">=", "threshold": None, "value": round_float(value), "passed": None}
    numeric_value = float(value)
    return {
        "enabled": True,
        "operator": ">=",
        "threshold": round(float(threshold), 8),
        "value": round(numeric_value, 8),
        "passed": numeric_value >= float(threshold),
    }


def round_metrics(metrics: dict[str, object]) -> dict[str, object]:
    """把指标数值整理成稳定 JSON 结构。"""

    return {key: round_float(value) for key, value in metrics.items()}


def round_float(value: object) -> object:
    """对浮点数统一保留 8 位，其他值原样返回。"""

    if isinstance(value, float):
        return round(value, 8)
    return value


def read_uint8_with_default(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取 0-255 阈值，空值使用默认值。"""

    if is_empty_parameter(raw_value):
        return default_value
    return require_uint8_int(raw_value, field_name=field_name)


def read_odd_kernel_with_default(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取可关闭的奇数 kernel size。"""

    if is_empty_parameter(raw_value):
        return default_value
    normalized_value = int(raw_value)
    if normalized_value < 1:
        raise InvalidRequestError(f"{field_name} 必须大于等于 1")
    if normalized_value % 2 == 0:
        raise InvalidRequestError(f"{field_name} 必须是奇数")
    return normalized_value


def read_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选正整数。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name=field_name)


def read_positive_int_with_default(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取正整数，空值使用默认值。"""

    if is_empty_parameter(raw_value):
        return default_value
    return require_positive_int(raw_value, field_name=field_name)


def read_optional_non_negative_float(
    raw_value: object,
    *,
    field_name: str,
    default_value: float | None = None,
) -> float | None:
    """读取可选非负数。"""

    if is_empty_parameter(raw_value):
        return default_value
    return require_non_negative_float(raw_value, field_name=field_name)


def read_optional_ratio(
    raw_value: object,
    *,
    field_name: str,
    default_value: float | None = None,
) -> float | None:
    """读取可选 0-1 比例。"""

    if is_empty_parameter(raw_value):
        return default_value
    normalized_value = require_non_negative_float(raw_value, field_name=field_name)
    if normalized_value > 1:
        raise InvalidRequestError(f"{field_name} 不能大于 1")
    return normalized_value


def read_ratio_with_default(raw_value: object, *, field_name: str, default_value: float) -> float:
    """读取 0-1 比例，空值使用默认值。"""

    normalized_value = read_optional_ratio(raw_value, field_name=field_name, default_value=default_value)
    if normalized_value is None:
        return default_value
    return normalized_value


def read_bool_with_default(raw_value: object, *, default_value: bool, field_name: str) -> bool:
    """读取 bool 参数，空值使用默认值。"""

    if is_empty_parameter(raw_value):
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return bool(raw_value)
