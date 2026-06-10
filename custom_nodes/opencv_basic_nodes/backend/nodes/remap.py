"""Remap 节点实现。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes._logic_node_support import build_value_payload, extract_value_by_path, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_optional_object_key,
    normalize_resize_interpolation,
    require_number,
    require_opencv_imports,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.remap"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按显式映射表重映射输入图片。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _source_object_key, image_matrix = load_image_matrix(request)
    mapping_object, mapping_source = _resolve_mapping_object(request)
    map_x, map_y, map_kind = _resolve_maps(
        request,
        mapping_object=mapping_object,
        np_module=np_module,
    )
    raw_interpolation = request.parameters.get("interpolation")
    interpolation = (
        cv2_module.INTER_LINEAR
        if raw_interpolation in {None, ""}
        else normalize_resize_interpolation(raw_interpolation, cv2_module=cv2_module)
    )
    border_mode = _resolve_border_mode(request.parameters.get("border_mode"), cv2_module=cv2_module)
    border_value = _read_optional_border_value(request.parameters.get("border_value"))
    border_value_argument = (
        (border_value, border_value, border_value) if len(image_matrix.shape) == 3 else border_value
    )
    remapped_image = cv2_module.remap(
        image_matrix,
        map_x,
        map_y,
        interpolation=interpolation,
        borderMode=border_mode,
        borderValue=border_value_argument,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=remapped_image,
        error_message="OpenCV remap 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="remap",
        output_extension=".png",
        width=int(remapped_image.shape[1]),
        height=int(remapped_image.shape[0]),
        media_type="image/png",
    )
    return {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "mapping_source": mapping_source,
                "map_kind": map_kind,
                "output_width": int(remapped_image.shape[1]),
                "output_height": int(remapped_image.shape[0]),
                "map_width": int(map_x.shape[1]),
                "map_height": int(map_x.shape[0]),
                "min_map_x": round(float(map_x.min()), 4),
                "max_map_x": round(float(map_x.max()), 4),
                "min_map_y": round(float(map_y.min()), 4),
                "max_map_y": round(float(map_y.max()), 4),
            }
        ),
    }


def _resolve_mapping_object(request: WorkflowNodeExecutionRequest) -> tuple[dict[str, object] | None, str]:
    """读取可选动态映射对象。"""

    raw_mapping_payload = request.input_values.get("mapping")
    if raw_mapping_payload is None:
        return None, "parameters"
    mapping_payload = require_value_payload(raw_mapping_payload, field_name="mapping")
    mapping_path = _read_optional_text(request.parameters.get("mapping_path"), field_name="mapping_path")
    resolved_value = (
        extract_value_by_path(root=mapping_payload["value"], path=mapping_path)
        if mapping_path is not None
        else mapping_payload["value"]
    )
    if not isinstance(resolved_value, dict):
        raise InvalidRequestError("remap 节点的 mapping 输入必须解析为对象")
    return dict(resolved_value), "input"


def _resolve_maps(
    request: WorkflowNodeExecutionRequest,
    *,
    mapping_object: dict[str, object] | None,
    np_module: Any,
):
    """解析 remap 所需 map_x/map_y。"""

    raw_map_xy = _resolve_mapping_field_value(
        mapping_object=mapping_object,
        field_name="map_xy",
        parameter_value=request.parameters.get("map_xy"),
    )
    if raw_map_xy is not None and raw_map_xy != "":
        return _normalize_map_xy(raw_map_xy, np_module=np_module)

    raw_map_x = _resolve_mapping_field_value(
        mapping_object=mapping_object,
        field_name="map_x",
        parameter_value=request.parameters.get("map_x"),
    )
    raw_map_y = _resolve_mapping_field_value(
        mapping_object=mapping_object,
        field_name="map_y",
        parameter_value=request.parameters.get("map_y"),
    )
    if raw_map_x is None or raw_map_x == "" or raw_map_y is None or raw_map_y == "":
        raise InvalidRequestError("remap 节点要求 map_xy，或 map_x 与 map_y 至少提供一种映射方式")
    return _normalize_separate_maps(raw_map_x=raw_map_x, raw_map_y=raw_map_y, np_module=np_module)


def _resolve_mapping_field_value(
    *,
    mapping_object: dict[str, object] | None,
    field_name: str,
    parameter_value: object,
) -> object:
    """优先读取 mapping 输入中的字段，否则回退到节点参数。"""

    if mapping_object is not None and mapping_object.get(field_name) is not None:
        return mapping_object.get(field_name)
    return parameter_value


def _normalize_map_xy(raw_value: object, *, np_module: Any):
    """把 HxWx2 的 map_xy 规范化为 OpenCV remap 需要的 map_x/map_y。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError("map_xy 必须是非空 HxWx2 数组")
    normalized_map_x: list[list[float]] = []
    normalized_map_y: list[list[float]] = []
    expected_row_width: int | None = None
    for row_index, row_value in enumerate(raw_value):
        if not isinstance(row_value, list) or not row_value:
            raise InvalidRequestError(f"map_xy[{row_index}] 必须是非空数组")
        if expected_row_width is None:
            expected_row_width = len(row_value)
        elif len(row_value) != expected_row_width:
            raise InvalidRequestError("map_xy 每一行长度必须一致")
        normalized_row_x: list[float] = []
        normalized_row_y: list[float] = []
        for column_index, point_value in enumerate(row_value):
            if not isinstance(point_value, list) or len(point_value) != 2:
                raise InvalidRequestError(f"map_xy[{row_index}][{column_index}] 必须是 [x, y]")
            normalized_row_x.append(
                require_number(point_value[0], field_name=f"map_xy[{row_index}][{column_index}][0]")
            )
            normalized_row_y.append(
                require_number(point_value[1], field_name=f"map_xy[{row_index}][{column_index}][1]")
            )
        normalized_map_x.append(normalized_row_x)
        normalized_map_y.append(normalized_row_y)
    return (
        np_module.array(normalized_map_x, dtype=np_module.float32),
        np_module.array(normalized_map_y, dtype=np_module.float32),
        "map_xy",
    )


def _normalize_separate_maps(*, raw_map_x: object, raw_map_y: object, np_module: Any):
    """把分离的 map_x/map_y 规范化为 OpenCV remap 所需 ndarray。"""

    normalized_map_x = _normalize_numeric_grid(raw_map_x, field_name="map_x", np_module=np_module)
    normalized_map_y = _normalize_numeric_grid(raw_map_y, field_name="map_y", np_module=np_module)
    if normalized_map_x.shape != normalized_map_y.shape:
        raise InvalidRequestError("map_x 与 map_y 的形状必须一致")
    return normalized_map_x, normalized_map_y, "map_x_map_y"


def _normalize_numeric_grid(raw_value: object, *, field_name: str, np_module: Any):
    """把 HxW 数值网格规范化为 float32 ndarray。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError(f"{field_name} 必须是非空二维数值数组")
    normalized_rows: list[list[float]] = []
    expected_row_width: int | None = None
    for row_index, row_value in enumerate(raw_value):
        if not isinstance(row_value, list) or not row_value:
            raise InvalidRequestError(f"{field_name}[{row_index}] 必须是非空数组")
        if expected_row_width is None:
            expected_row_width = len(row_value)
        elif len(row_value) != expected_row_width:
            raise InvalidRequestError(f"{field_name} 每一行长度必须一致")
        normalized_rows.append(
            [
                require_number(cell_value, field_name=f"{field_name}[{row_index}][{column_index}]")
                for column_index, cell_value in enumerate(row_value)
            ]
        )
    return np_module.array(normalized_rows, dtype=np_module.float32)


def _resolve_border_mode(raw_value: object, *, cv2_module) -> int:
    """解析边界填充模式。"""

    if raw_value in {None, ""}:
        return cv2_module.BORDER_CONSTANT
    if not isinstance(raw_value, str):
        raise InvalidRequestError("border_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value == "constant":
        return cv2_module.BORDER_CONSTANT
    if normalized_value == "replicate":
        return cv2_module.BORDER_REPLICATE
    if normalized_value == "reflect":
        return cv2_module.BORDER_REFLECT
    if normalized_value == "reflect101":
        return cv2_module.BORDER_REFLECT_101
    if normalized_value == "wrap":
        return cv2_module.BORDER_WRAP
    raise InvalidRequestError("border_mode 仅支持 constant、replicate、reflect、reflect101 或 wrap")


def _read_optional_border_value(raw_value: object) -> int:
    """读取边界填充值。"""

    if raw_value in {None, ""}:
        return 0
    return require_uint8_int(raw_value, field_name="border_value")


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本参数。"""

    if raw_value in {None, ""}:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None
