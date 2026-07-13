"""Image refs 批量槽位指标节点和公共工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_number_control,
    build_numeric_control,
    build_select_control,
    is_debug_image_panel_enabled,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import load_image_matrix_from_payload, register_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.image-refs-slot-metrics"
NODE_DISPLAY_NAME = "image-refs-slot-metrics"


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


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算 image-refs.v1 图片集合的槽位指标。

    该节点只负责输出稳定的 per-slot metrics，不直接做 empty / occupied 判断。
    这样现场调试时可以先看指标，再把指标接到空槽、有料或其他规则节点中。
    """

    cv2_module, np_module = require_opencv_imports()
    image_refs_payload = require_image_refs_payload(request.input_values.get("images"))
    config = read_slot_metric_config(request, node_display_name=NODE_DISPLAY_NAME)
    source_items = list(image_refs_payload["items"])
    if config.max_items is not None:
        source_items = source_items[: config.max_items]

    metric_items: list[dict[str, object]] = []
    debug_records: list[dict[str, object]] = []
    for item_index, image_item in enumerate(source_items, start=1):
        image_payload, image_matrix = load_image_matrix_from_payload(
            request,
            image_payload=image_item,
            cv2_module=cv2_module,
            np_module=np_module,
            copy_raw=False,
        )
        metric_item = build_slot_metric_item(
            cv2_module=cv2_module,
            np_module=np_module,
            image_payload=image_payload,
            image_matrix=image_matrix,
            item_index=item_index,
            config=config,
            node_display_name=NODE_DISPLAY_NAME,
        )
        metric_items.append(metric_item)
        debug_records.append(
            {
                "image_payload": image_payload,
                "image_matrix": image_matrix,
                "item": metric_item,
            }
        )

    payload = {
        "format_id": "amvision.image-refs-slot-metrics.v1",
        "count": len(metric_items),
        "total_count": int(image_refs_payload.get("count", len(image_refs_payload["items"]))),
        "rules": build_slot_metric_rule_summary(config),
        "items": metric_items,
    }
    return {
        "summary": build_value_payload(payload),
        "body": {
            "type": "image-refs-slot-metrics",
            **payload,
        },
        **build_slot_metric_debug_preview_output(
            request,
            cv2_module=cv2_module,
            np_module=np_module,
            image_records=debug_records,
            title="Image Refs Slot Metrics",
            controls=build_slot_metric_controls(config),
            artifact_name="slot-metrics-debug-preview",
        ),
    }


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


def build_slot_metric_rule_summary(config: ImageRefsSlotMetricConfig) -> dict[str, object]:
    """返回槽位指标计算规则。"""

    return {
        "max_items": config.max_items,
        "dark_threshold": config.dark_threshold,
        "bright_threshold": config.bright_threshold,
        "canny_low_threshold": config.canny_low_threshold,
        "canny_high_threshold": config.canny_high_threshold,
        "dark_morph_kernel_size": config.dark_morph_kernel_size,
        "dark_component_min_area": config.dark_component_min_area,
    }


def build_slot_metric_controls(config: ImageRefsSlotMetricConfig) -> list[dict[str, object]]:
    """构造槽位指标节点和规则节点共用的 ImageViewer 调参控件。"""

    return [
        build_number_control("max_items", "Max Items", config.max_items, min_value=1, step=1),
        build_numeric_control("dark_threshold", "Dark Threshold", config.dark_threshold, min_value=0, max_value=255, step=1),
        build_numeric_control(
            "bright_threshold",
            "Bright Threshold",
            config.bright_threshold,
            min_value=0,
            max_value=255,
            step=1,
        ),
        build_numeric_control(
            "canny_low_threshold",
            "Canny Low",
            config.canny_low_threshold,
            min_value=0,
            max_value=255,
            step=1,
        ),
        build_numeric_control(
            "canny_high_threshold",
            "Canny High",
            config.canny_high_threshold,
            min_value=0,
            max_value=255,
            step=1,
        ),
        build_select_control(
            "dark_morph_kernel_size",
            "Dark Morph Kernel",
            config.dark_morph_kernel_size,
            options=((1, "1 / off"), (3, "3"), (5, "5"), (7, "7"), (9, "9"), (11, "11")),
        ),
        build_number_control(
            "dark_component_min_area",
            "Dark Component Min Area",
            config.dark_component_min_area,
            min_value=0,
            step=1,
        ),
    ]


def build_slot_metric_debug_preview_output(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: Any,
    np_module: Any,
    image_records: list[dict[str, object]],
    title: str,
    controls: list[dict[str, object]],
    artifact_name: str,
    ok_decisions: tuple[str, ...] = (),
    bad_decisions: tuple[str, ...] = (),
) -> dict[str, object]:
    """构造批量槽位指标调试图。

    只有编辑态 Preview Run 显式打开 debug image panel 时才会生成 contact sheet。
    生产 runtime 不会进入这里，避免批量裁剪图被再次编码。
    """

    if not is_debug_image_panel_enabled(request) or not image_records:
        return {}
    contact_sheet = _build_slot_metric_contact_sheet(
        cv2_module=cv2_module,
        np_module=np_module,
        image_records=image_records,
        ok_decisions=ok_decisions,
        bad_decisions=bad_decisions,
    )
    preview_image_payload = register_image_matrix(
        request,
        image_matrix=contact_sheet,
        created_by_node_id=request.node_id,
    )
    return build_debug_image_preview_output(
        request,
        image_payload=preview_image_payload,
        title=title,
        interaction=build_debug_panel_interaction(tools=(), controls=controls),
        artifact_name=artifact_name,
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


def _build_slot_metric_contact_sheet(
    *,
    cv2_module: Any,
    np_module: Any,
    image_records: list[dict[str, object]],
    ok_decisions: tuple[str, ...],
    bad_decisions: tuple[str, ...],
) -> Any:
    """把批量槽位图片和关键指标绘制成一张调试 contact sheet。"""

    count = len(image_records)
    columns = min(6, max(1, int(math.ceil(math.sqrt(count)))))
    rows = int(math.ceil(count / columns))
    tile_width = 220
    tile_height = 140
    label_height = 78
    gap = 8
    canvas_width = columns * tile_width + (columns + 1) * gap
    canvas_height = rows * (tile_height + label_height) + (rows + 1) * gap
    canvas = np_module.full((canvas_height, canvas_width, 3), 32, dtype=np_module.uint8)

    for record_index, record in enumerate(image_records):
        row = record_index // columns
        column = record_index % columns
        origin_x = gap + column * (tile_width + gap)
        origin_y = gap + row * (tile_height + label_height + gap)
        image_matrix = _normalize_preview_matrix(cv2_module=cv2_module, image_matrix=record["image_matrix"])
        resized_image = _fit_image_to_tile(
            cv2_module=cv2_module,
            np_module=np_module,
            image_matrix=image_matrix,
            tile_width=tile_width,
            tile_height=tile_height,
        )
        image_y = origin_y
        image_x = origin_x
        canvas[image_y : image_y + tile_height, image_x : image_x + tile_width] = resized_image
        item = record["item"]
        border_color = _decision_color(str(item.get("decision") or ""), ok_decisions=ok_decisions, bad_decisions=bad_decisions)
        cv2_module.rectangle(
            canvas,
            (origin_x, origin_y),
            (origin_x + tile_width - 1, origin_y + tile_height + label_height - 1),
            border_color,
            2,
        )
        _draw_slot_metric_labels(
            cv2_module=cv2_module,
            canvas=canvas,
            item=item,
            origin_x=origin_x + 8,
            origin_y=origin_y + tile_height + 18,
            max_width=tile_width - 16,
            color=border_color,
        )
    return canvas


def _normalize_preview_matrix(*, cv2_module: Any, image_matrix: Any) -> Any:
    """把灰度或带 alpha 图片整理成 BGR 预览图。"""

    if len(image_matrix.shape) == 2:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_GRAY2BGR)
    if image_matrix.shape[2] == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2BGR)
    return image_matrix


def _fit_image_to_tile(
    *,
    cv2_module: Any,
    np_module: Any,
    image_matrix: Any,
    tile_width: int,
    tile_height: int,
) -> Any:
    """按比例缩放图片并居中放入固定 tile。"""

    height, width = image_matrix.shape[:2]
    scale = min(tile_width / max(width, 1), tile_height / max(height, 1))
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    resized = cv2_module.resize(image_matrix, (resized_width, resized_height), interpolation=cv2_module.INTER_AREA)
    tile = np_module.full((tile_height, tile_width, 3), 18, dtype=np_module.uint8)
    offset_x = (tile_width - resized_width) // 2
    offset_y = (tile_height - resized_height) // 2
    tile[offset_y : offset_y + resized_height, offset_x : offset_x + resized_width] = resized
    return tile


def _decision_color(
    decision: str,
    *,
    ok_decisions: tuple[str, ...],
    bad_decisions: tuple[str, ...],
) -> tuple[int, int, int]:
    """按判断结果选择 BGR 颜色。"""

    if decision in ok_decisions:
        return (80, 190, 80)
    if decision in bad_decisions:
        return (80, 80, 230)
    if decision == "unknown":
        return (40, 180, 230)
    return (220, 180, 60)


def _draw_slot_metric_labels(
    *,
    cv2_module: Any,
    canvas: Any,
    item: dict[str, object],
    origin_x: int,
    origin_y: int,
    max_width: int,
    color: tuple[int, int, int],
) -> None:
    """把槽位序号、判断和关键指标写到 contact sheet。"""

    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    roi_id = str(item.get("roi_id") or f"#{item.get('index')}")
    decision = str(item.get("decision") or "metrics")
    failed_rules = item.get("failed_rules") if isinstance(item.get("failed_rules"), list) else []
    title = f"{int(item.get('index') or 0):02d} {roi_id}"
    if decision and decision != "metrics":
        title = f"{title} {decision}"
    lines = [
        title,
        "std {:.1f} | dark {:.3f}".format(
            float(metrics.get("std_gray", 0) or 0),
            float(metrics.get("dark_ratio", 0) or 0),
        ),
        "edge {:.3f} | comp {:.3f}".format(
            float(metrics.get("edge_density", 0) or 0),
            float(metrics.get("dark_component_area_ratio", 0) or 0),
        ),
        "max {:.3f}{}".format(
            float(metrics.get("largest_dark_component_area_ratio", 0) or 0),
            f" fail={len(failed_rules)}" if failed_rules else "",
        ),
    ]
    font_scale = 0.36
    thickness = 1
    for line_index, line in enumerate(lines):
        display_line = _truncate_text_to_pixel_width(
            cv2_module=cv2_module,
            text=line,
            max_width=max_width,
            font_scale=font_scale,
            thickness=thickness,
        )
        cv2_module.putText(
            canvas,
            display_line,
            (origin_x, origin_y + line_index * 16),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color if line_index == 0 else (225, 225, 225),
            thickness,
            cv2_module.LINE_AA,
        )


def _truncate_text_to_pixel_width(
    *,
    cv2_module: Any,
    text: str,
    max_width: int,
    font_scale: float,
    thickness: int,
) -> str:
    """按 OpenCV 实际绘制宽度截断文本，避免 contact sheet 字符串溢出到相邻 tile。"""

    if max_width <= 0:
        return ""
    font_face = cv2_module.FONT_HERSHEY_SIMPLEX
    text_width = cv2_module.getTextSize(text, font_face, font_scale, thickness)[0][0]
    if text_width <= max_width:
        return text

    suffix = "..."
    suffix_width = cv2_module.getTextSize(suffix, font_face, font_scale, thickness)[0][0]
    if suffix_width >= max_width:
        return ""
    result = text
    while result:
        candidate = result + suffix
        candidate_width = cv2_module.getTextSize(candidate, font_face, font_scale, thickness)[0][0]
        if candidate_width <= max_width:
            return candidate
        result = result[:-1]
    return suffix


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
