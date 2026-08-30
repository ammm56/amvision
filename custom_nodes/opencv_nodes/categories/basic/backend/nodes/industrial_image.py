"""工业二维视觉常用图片创建、转换、组合和拼接节点。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_bool,
    read_choice,
    read_float,
    read_int,
    read_number_list,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_typed_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_image_refs_payload,
)

IMAGE_CREATE_NODE_TYPE_ID = "custom.opencv.image-create"
IMAGE_TYPE_CONVERT_NODE_TYPE_ID = "custom.opencv.image-type-convert"
IMAGE_TRANSLATE_NODE_TYPE_ID = "custom.opencv.image-translate"
IMAGE_COMPOSITE_NODE_TYPE_ID = "custom.opencv.image-composite"
IMAGE_CONCAT_NODE_TYPE_ID = "custom.opencv.image-concat"
IMAGE_STITCH_NODE_TYPE_ID = "custom.opencv.image-stitch"

_MAX_IMAGE_ELEMENTS = 1024 * 1024 * 1024
_SUPPORTED_DTYPES = {"uint8", "uint16", "float32"}


def handle_image_create(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按尺寸、通道、dtype 和填充值创建图片。"""

    _, np_module = require_opencv_imports()
    width = read_int(
        request.parameters.get("width"),
        field_name="width",
        default=640,
        minimum=1,
        maximum=1_000_000,
    )
    height = read_int(
        request.parameters.get("height"),
        field_name="height",
        default=480,
        minimum=1,
        maximum=1_000_000,
    )
    channels = read_int(
        request.parameters.get("channels"),
        field_name="channels",
        default=3,
    )
    if channels not in {1, 3, 4}:
        raise InvalidRequestError("channels 只支持 1、3 或 4")
    dtype = read_choice(
        request.parameters.get("dtype"),
        field_name="dtype",
        choices=_SUPPORTED_DTYPES,
        default="uint8",
    )
    if width * height * channels > _MAX_IMAGE_ELEMENTS:
        raise InvalidRequestError(
            "创建图片超过单张图片元素上限",
            details={
                "width": width,
                "height": height,
                "channels": channels,
                "max_elements": _MAX_IMAGE_ELEMENTS,
            },
        )
    fill_values = _read_fill_values(
        request.parameters.get("fill_value"),
        channels=channels,
    )
    _validate_fill_values(fill_values, dtype=dtype)
    shape = (height, width) if channels == 1 else (height, width, channels)
    fill_value: float | tuple[float, ...] = (
        fill_values[0] if channels == 1 else tuple(fill_values)
    )
    matrix = np_module.full(shape, fill_value, dtype=np_module.dtype(dtype))
    return {"image": _typed_output(request, matrix)}


def handle_image_type_convert(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """显式转换图片 dtype、通道布局和数值范围。"""

    cv2_module, np_module = require_opencv_imports()
    _, _, source = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    target_dtype = read_choice(
        request.parameters.get("target_dtype"),
        field_name="target_dtype",
        choices=_SUPPORTED_DTYPES,
        default="uint8",
    )
    channel_layout = read_choice(
        request.parameters.get("channel_layout"),
        field_name="channel_layout",
        choices={"keep", "gray", "bgr", "bgra"},
        default="keep",
    )
    range_mode = read_choice(
        request.parameters.get("range_mode"),
        field_name="range_mode",
        choices={"preserve", "normalize", "scale-offset"},
        default="preserve",
    )
    converted_channels = _convert_channel_layout(
        source,
        channel_layout=channel_layout,
        cv2_module=cv2_module,
    )
    converted = _convert_numeric_range(
        converted_channels,
        target_dtype=target_dtype,
        range_mode=range_mode,
        scale=read_float(
            request.parameters.get("scale"),
            field_name="scale",
            default=1.0,
        ),
        offset=read_float(
            request.parameters.get("offset"),
            field_name="offset",
            default=0.0,
        ),
        np_module=np_module,
    )
    return {"image": _typed_output(request, converted)}


def handle_image_translate(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按像素偏移平移图片并保留输入 dtype。"""

    cv2_module, np_module = require_opencv_imports()
    _, _, source = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    offset_x = read_float(
        request.parameters.get("offset_x"),
        field_name="offset_x",
        default=0.0,
    )
    offset_y = read_float(
        request.parameters.get("offset_y"),
        field_name="offset_y",
        default=0.0,
    )
    interpolation = read_choice(
        request.parameters.get("interpolation"),
        field_name="interpolation",
        choices={"nearest", "linear", "cubic", "lanczos"},
        default="linear",
    )
    border_mode = read_choice(
        request.parameters.get("border_mode"),
        field_name="border_mode",
        choices={"constant", "replicate", "reflect", "reflect-101", "wrap"},
        default="constant",
    )
    channels = 1 if len(source.shape) == 2 else int(source.shape[2])
    border_values = _read_fill_values(
        request.parameters.get("border_value"),
        channels=channels,
    )
    transform = np_module.asarray(
        [[1.0, 0.0, offset_x], [0.0, 1.0, offset_y]],
        dtype=np_module.float64,
    )
    output = cv2_module.warpAffine(
        source,
        transform,
        (int(source.shape[1]), int(source.shape[0])),
        flags={
            "nearest": cv2_module.INTER_NEAREST,
            "linear": cv2_module.INTER_LINEAR,
            "cubic": cv2_module.INTER_CUBIC,
            "lanczos": cv2_module.INTER_LANCZOS4,
        }[interpolation],
        borderMode={
            "constant": cv2_module.BORDER_CONSTANT,
            "replicate": cv2_module.BORDER_REPLICATE,
            "reflect": cv2_module.BORDER_REFLECT,
            "reflect-101": cv2_module.BORDER_REFLECT_101,
            "wrap": cv2_module.BORDER_WRAP,
        }[border_mode],
        borderValue=border_values[0] if channels == 1 else tuple(border_values),
    )
    return {"image": _typed_output(request, output)}


def handle_image_composite(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按位置、可选 mask 和 alpha 把 overlay 组合到 base 图片。"""

    cv2_module, np_module = require_opencv_imports()
    _, _, base = load_image_matrix(
        request,
        input_name="base_image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    _, _, overlay = load_image_matrix(
        request,
        input_name="overlay_image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    _require_same_image_type(base, overlay, field_name="base_image/overlay_image")
    mask = None
    if request.input_values.get("mask") is not None:
        _, _, mask = load_image_matrix(
            request,
            input_name="mask",
            imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
        )
        if tuple(mask.shape[:2]) != tuple(overlay.shape[:2]):
            raise InvalidRequestError("mask 尺寸必须与 overlay_image 一致")
    offset_x = read_int(
        request.parameters.get("offset_x"),
        field_name="offset_x",
        default=0,
    )
    offset_y = read_int(
        request.parameters.get("offset_y"),
        field_name="offset_y",
        default=0,
    )
    alpha = read_float(
        request.parameters.get("alpha"),
        field_name="alpha",
        default=1.0,
        minimum=0.0,
        maximum=1.0,
    )
    output = base.copy()
    base_slice, overlay_slice = _resolve_composite_slices(
        base_shape=base.shape,
        overlay_shape=overlay.shape,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    if base_slice is None or overlay_slice is None:
        if read_bool(
            request.parameters.get("require_overlap"),
            field_name="require_overlap",
            default=True,
        ):
            raise InvalidRequestError("overlay_image 与 base_image 没有重叠区域")
        return {"image": _typed_output(request, output)}
    base_region = output[base_slice]
    overlay_region = overlay[overlay_slice]
    mask_region = mask[overlay_slice[:2]] if mask is not None else None
    if mask_region is None:
        if alpha <= 0.0:
            return {"image": _typed_output(request, output)}
        if alpha >= 1.0:
            output[base_slice] = overlay_region
            return {"image": _typed_output(request, output)}
        blended = cv2_module.addWeighted(
            base_region,
            1.0 - alpha,
            overlay_region,
            alpha,
            0.0,
        )
    else:
        blend_weight = _build_blend_weight(
            mask_region,
            alpha=alpha,
            channel_count=1 if len(base.shape) == 2 else int(base.shape[2]),
            np_module=np_module,
        )
        base_working = base_region.astype(np_module.float32)
        overlay_working = overlay_region.astype(np_module.float32)
        blended = base_working + (overlay_working - base_working) * blend_weight
    output[base_slice] = _cast_numeric_image(
        blended,
        target_dtype=str(base.dtype),
        np_module=np_module,
    )
    return {"image": _typed_output(request, output)}


def handle_image_concat(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按水平或垂直方向拼接 image-refs 集合。"""

    cv2_module, np_module = require_opencv_imports()
    images = _load_image_collection(request, cv2_module=cv2_module, np_module=np_module)
    _require_collection_compatible(images)
    axis = read_choice(
        request.parameters.get("axis"),
        field_name="axis",
        choices={"horizontal", "vertical"},
        default="horizontal",
    )
    alignment = read_choice(
        request.parameters.get("alignment"),
        field_name="alignment",
        choices={"start", "center", "end"},
        default="center",
    )
    gap = read_int(
        request.parameters.get("gap"),
        field_name="gap",
        default=0,
        minimum=0,
        maximum=65535,
    )
    channels = 1 if len(images[0].shape) == 2 else int(images[0].shape[2])
    fill_values = _read_fill_values(
        request.parameters.get("fill_value"),
        channels=channels,
    )
    _validate_fill_values(fill_values, dtype=str(images[0].dtype))
    output = _concat_images(
        images,
        axis=axis,
        alignment=alignment,
        gap=gap,
        fill_values=fill_values,
        np_module=np_module,
    )
    return {"image": _typed_output(request, output)}


def handle_image_stitch(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用 OpenCV Stitcher 完成特征配准拼接并返回诊断。"""

    cv2_module, np_module = require_opencv_imports()
    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    images = _load_image_collection(request, cv2_module=cv2_module, np_module=np_module)
    if len(images) < 2:
        raise InvalidRequestError("image-stitch 至少要求两张图片")
    if len(images) > 32:
        raise InvalidRequestError("image-stitch 单次最多支持 32 张图片")
    normalized_images = []
    for image in images:
        if str(image.dtype) != "uint8":
            raise InvalidRequestError("image-stitch 当前要求 uint8 图片")
        if len(image.shape) == 2:
            image = cv2_module.cvtColor(image, cv2_module.COLOR_GRAY2BGR)
        elif int(image.shape[2]) == 4:
            image = cv2_module.cvtColor(image, cv2_module.COLOR_BGRA2BGR)
        normalized_images.append(image)
    mode = read_choice(
        request.parameters.get("mode"),
        field_name="mode",
        choices={"panorama", "scans"},
        default="panorama",
    )
    stitcher = cv2_module.Stitcher_create(
        cv2_module.Stitcher_PANORAMA
        if mode == "panorama"
        else cv2_module.Stitcher_SCANS
    )
    confidence_threshold = read_float(
        request.parameters.get("confidence_threshold"),
        field_name="confidence_threshold",
        default=1.0,
        minimum=0.0,
    )
    stitcher.setPanoConfidenceThresh(confidence_threshold)
    status, output = stitcher.stitch(normalized_images)
    execution_control.raise_if_cancelled_or_expired()
    status_names = {
        int(cv2_module.Stitcher_OK): "ok",
        int(cv2_module.Stitcher_ERR_NEED_MORE_IMGS): "need-more-images",
        int(cv2_module.Stitcher_ERR_HOMOGRAPHY_EST_FAIL): "homography-estimation-failed",
        int(cv2_module.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL): "camera-adjustment-failed",
    }
    if int(status) != int(cv2_module.Stitcher_OK) or output is None:
        raise InvalidRequestError(
            "image-stitch 无法完成图片拼接",
            details={
                "status": int(status),
                "status_name": status_names.get(int(status), "unknown"),
                "image_count": len(images),
            },
        )
    diagnostics = {
        "format_id": "amvision.image-stitch-diagnostics.v1",
        "status": "ok",
        "mode": mode,
        "image_count": len(images),
        "output_width": int(output.shape[1]),
        "output_height": int(output.shape[0]),
        "confidence_threshold": confidence_threshold,
    }
    return {
        "image": _typed_output(request, output),
        "diagnostics": build_value_payload(diagnostics),
    }


def _typed_output(request: WorkflowNodeExecutionRequest, matrix: Any) -> dict[str, object]:
    """输出保留 dtype 的连续执行期图片。"""

    return build_typed_output_image_matrix_payload(
        request,
        image_matrix=matrix,
    )


def _read_fill_values(value: object, *, channels: int) -> list[float]:
    """读取标量或逐通道填充值。"""

    if value is None:
        return [0.0] * channels
    if isinstance(value, bool):
        raise InvalidRequestError("填充值必须是数字或数字数组")
    if isinstance(value, int | float):
        return [float(value)] * channels
    values = read_number_list(
        value,
        field_name="fill_value",
        exact_length=channels,
    )
    return values


def _validate_fill_values(values: list[float], *, dtype: str) -> None:
    """校验填充值是否能由目标 dtype 表示。"""

    if dtype == "uint8" and any(value < 0 or value > 255 for value in values):
        raise InvalidRequestError("uint8 填充值必须位于 0..255")
    if dtype == "uint16" and any(value < 0 or value > 65535 for value in values):
        raise InvalidRequestError("uint16 填充值必须位于 0..65535")


def _convert_channel_layout(image: Any, *, channel_layout: str, cv2_module: Any) -> Any:
    """按 OpenCV BGR 约定转换 HW/HWC 通道布局。"""

    if channel_layout == "keep":
        return image
    channels = 1 if len(image.shape) == 2 else int(image.shape[2])
    if channel_layout == "gray":
        if channels == 1:
            return image
        return cv2_module.cvtColor(
            image,
            cv2_module.COLOR_BGRA2GRAY if channels == 4 else cv2_module.COLOR_BGR2GRAY,
        )
    if channel_layout == "bgr":
        if channels == 3:
            return image
        return cv2_module.cvtColor(
            image,
            cv2_module.COLOR_GRAY2BGR if channels == 1 else cv2_module.COLOR_BGRA2BGR,
        )
    if channels == 4:
        return image
    return cv2_module.cvtColor(
        image,
        cv2_module.COLOR_GRAY2BGRA if channels == 1 else cv2_module.COLOR_BGR2BGRA,
    )


def _convert_numeric_range(
    image: Any,
    *,
    target_dtype: str,
    range_mode: str,
    scale: float,
    offset: float,
    np_module: Any,
) -> Any:
    """按明确策略转换图片数值范围。"""

    if range_mode == "preserve":
        if str(image.dtype) == target_dtype:
            return np_module.ascontiguousarray(image)
        if target_dtype == "float32":
            return image.astype(np_module.float32)
        if np_module.issubdtype(image.dtype, np_module.integer):
            maximum = 255 if target_dtype == "uint8" else 65535
            return np_module.clip(image, 0, maximum).astype(np_module.dtype(target_dtype))

    working = image.astype(np_module.float32)
    if range_mode == "normalize":
        source_min = float(np_module.min(working))
        source_max = float(np_module.max(working))
        if source_max <= source_min:
            working = np_module.zeros_like(working)
        else:
            working = (working - source_min) / (source_max - source_min)
        if target_dtype == "uint8":
            working *= 255.0
        elif target_dtype == "uint16":
            working *= 65535.0
    elif range_mode == "scale-offset":
        working = working * scale + offset
    return _cast_numeric_image(
        working,
        target_dtype=target_dtype,
        np_module=np_module,
    )


def _cast_numeric_image(image: Any, *, target_dtype: str, np_module: Any) -> Any:
    """使用确定性裁剪和四舍五入转换整数图片。"""

    if target_dtype == "float32":
        return image.astype(np_module.float32)
    maximum = 255.0 if target_dtype == "uint8" else 65535.0
    return np_module.rint(np_module.clip(image, 0.0, maximum)).astype(
        np_module.dtype(target_dtype)
    )


def _require_same_image_type(first: Any, second: Any, *, field_name: str) -> None:
    """校验组合图片的 dtype 和通道数一致。"""

    first_channels = 1 if len(first.shape) == 2 else int(first.shape[2])
    second_channels = 1 if len(second.shape) == 2 else int(second.shape[2])
    if str(first.dtype) != str(second.dtype) or first_channels != second_channels:
        raise InvalidRequestError(
            f"{field_name} 的 dtype 和通道数必须一致",
            details={
                "first_dtype": str(first.dtype),
                "second_dtype": str(second.dtype),
                "first_channels": first_channels,
                "second_channels": second_channels,
            },
        )


def _resolve_composite_slices(
    *,
    base_shape: tuple[int, ...],
    overlay_shape: tuple[int, ...],
    offset_x: int,
    offset_y: int,
) -> tuple[tuple[slice, ...] | None, tuple[slice, ...] | None]:
    """计算允许负偏移的 base/overlay 交集切片。"""

    base_height, base_width = int(base_shape[0]), int(base_shape[1])
    overlay_height, overlay_width = int(overlay_shape[0]), int(overlay_shape[1])
    base_x0 = max(0, offset_x)
    base_y0 = max(0, offset_y)
    base_x1 = min(base_width, offset_x + overlay_width)
    base_y1 = min(base_height, offset_y + overlay_height)
    if base_x1 <= base_x0 or base_y1 <= base_y0:
        return None, None
    overlay_x0 = base_x0 - offset_x
    overlay_y0 = base_y0 - offset_y
    overlay_x1 = overlay_x0 + (base_x1 - base_x0)
    overlay_y1 = overlay_y0 + (base_y1 - base_y0)
    trailing = (slice(None),) if len(base_shape) == 3 else ()
    return (
        (slice(base_y0, base_y1), slice(base_x0, base_x1), *trailing),
        (
            slice(overlay_y0, overlay_y1),
            slice(overlay_x0, overlay_x1),
            *trailing,
        ),
    )


def _build_blend_weight(
    mask: Any | None,
    *,
    alpha: float,
    channel_count: int,
    np_module: Any,
) -> Any:
    """把可选 mask 转换为 0..1 blend 权重。"""

    if mask is None:
        return float(alpha)
    mask_values = mask.astype(np_module.float32)
    mask_maximum = float(np_module.max(mask_values)) if mask_values.size else 0.0
    if mask_maximum > 1.0:
        mask_values /= 255.0
    mask_values = np_module.clip(mask_values, 0.0, 1.0) * float(alpha)
    if channel_count > 1:
        mask_values = mask_values[..., np_module.newaxis]
    return mask_values


def _load_image_collection(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: Any,
    np_module: Any,
) -> list[Any]:
    """按 image-refs.v1 顺序读取图片集合。"""

    payload = require_image_refs_payload(request.input_values.get("images"))
    items = payload["items"]
    if not items:
        raise InvalidRequestError("images 至少包含一张图片")
    execution_control = build_node_execution_control(request)
    matrices = []
    for item in items:
        execution_control.raise_if_cancelled_or_expired()
        _, matrix = load_image_matrix_from_payload(
            request,
            image_payload=item,
            cv2_module=cv2_module,
            np_module=np_module,
            imdecode_flags=cv2_module.IMREAD_UNCHANGED,
            copy_raw=False,
        )
        matrices.append(matrix)
    return matrices


def _require_collection_compatible(images: list[Any]) -> None:
    """校验规则拼接图片具有相同 dtype 和通道数。"""

    first = images[0]
    for image in images[1:]:
        _require_same_image_type(first, image, field_name="images")


def _concat_images(
    images: list[Any],
    *,
    axis: str,
    alignment: str,
    gap: int,
    fill_values: list[float],
    np_module: Any,
) -> Any:
    """在一次目标分配中完成规则拼接。"""

    horizontal = axis == "horizontal"
    output_height = (
        max(int(image.shape[0]) for image in images)
        if horizontal
        else sum(int(image.shape[0]) for image in images) + gap * (len(images) - 1)
    )
    output_width = (
        sum(int(image.shape[1]) for image in images) + gap * (len(images) - 1)
        if horizontal
        else max(int(image.shape[1]) for image in images)
    )
    channels = 1 if len(images[0].shape) == 2 else int(images[0].shape[2])
    shape = (
        (output_height, output_width)
        if channels == 1
        else (output_height, output_width, channels)
    )
    fill_value: float | tuple[float, ...] = (
        fill_values[0] if channels == 1 else tuple(fill_values)
    )
    output = np_module.full(shape, fill_value, dtype=images[0].dtype)
    cursor = 0
    for image in images:
        height, width = int(image.shape[0]), int(image.shape[1])
        cross_space = (output_height - height) if horizontal else (output_width - width)
        cross_offset = {
            "start": 0,
            "center": cross_space // 2,
            "end": cross_space,
        }[alignment]
        if horizontal:
            output[cross_offset : cross_offset + height, cursor : cursor + width] = image
            cursor += width + gap
        else:
            output[cursor : cursor + height, cross_offset : cross_offset + width] = image
            cursor += height + gap
    return output


INDUSTRIAL_IMAGE_NODE_HANDLERS = (
    (IMAGE_CREATE_NODE_TYPE_ID, handle_image_create),
    (IMAGE_TYPE_CONVERT_NODE_TYPE_ID, handle_image_type_convert),
    (IMAGE_TRANSLATE_NODE_TYPE_ID, handle_image_translate),
    (IMAGE_COMPOSITE_NODE_TYPE_ID, handle_image_composite),
    (IMAGE_CONCAT_NODE_TYPE_ID, handle_image_concat),
    (IMAGE_STITCH_NODE_TYPE_ID, handle_image_stitch),
)


__all__ = ["INDUSTRIAL_IMAGE_NODE_HANDLERS"]
