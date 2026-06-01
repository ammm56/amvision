"""SAHI 大图切片推理节点。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import count
from typing import Iterable

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import (
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_float_parameter,
    get_optional_int_pair_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.nodes.runtime_support import load_image_bytes
from backend.service.application.deployments import PublishedInferenceRequest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3
_DEFAULT_SLICE_WIDTH = 640
_DEFAULT_SLICE_HEIGHT = 640
_DEFAULT_OVERLAP_WIDTH = 64
_DEFAULT_OVERLAP_HEIGHT = 64
_DEFAULT_IOU_THRESHOLD = 0.5
_DEFAULT_THREAD_WORKERS = 1
_MERGE_MODE_NMS = "nms"
_MERGE_MODE_NMM = "nmm"
_MERGE_MODE_NONE = "none"
_SUPPORTED_MERGE_MODES = frozenset({_MERGE_MODE_NMS, _MERGE_MODE_NMM, _MERGE_MODE_NONE})
_SLICE_IMAGE_HANDLE_COUNTER = count(1)


@dataclass(frozen=True)
class _SliceWindow:
    """描述单个切片窗口。"""

    index: int
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        """返回切片宽度。"""

        return self.x2 - self.x1

    @property
    def height(self) -> int:
        """返回切片高度。"""

        return self.y2 - self.y1


def _sahi_inference_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行大图切片推理并合并 detection 结果。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    deployment_instance_id = require_str_parameter(request, "deployment_instance_id")
    score_threshold = get_optional_float_parameter(request, "score_threshold") or _DEFAULT_INFERENCE_SCORE_THRESHOLD
    auto_start_process = get_optional_bool_parameter(request, "auto_start_process")
    save_result_image = get_optional_bool_parameter(request, "save_result_image")
    return_preview_image_base64 = get_optional_bool_parameter(request, "return_preview_image_base64")
    thread_workers = _resolve_thread_workers(request)
    merge_mode = _resolve_merge_mode(request)
    iou_threshold = get_optional_float_parameter(request, "iou_threshold")
    normalized_iou_threshold = _normalize_iou_threshold(iou_threshold)
    slice_width, slice_height = _resolve_slice_size(request)
    overlap_width, overlap_height = _resolve_overlap_size(
        request,
        slice_width=slice_width,
        slice_height=slice_height,
    )

    normalized_image_payload, source_image_bytes = load_image_bytes(request)
    source_image = _decode_source_image(source_image_bytes)
    image_height = int(source_image.shape[0])
    image_width = int(source_image.shape[1])
    slice_windows = _build_slice_windows(
        image_width=image_width,
        image_height=image_height,
        slice_width=slice_width,
        slice_height=slice_height,
        overlap_width=overlap_width,
        overlap_height=overlap_height,
    )
    gateway = runtime_context.build_published_inference_gateway()
    extra_options = get_optional_dict_parameter(request, "extra_options")
    preferred_media_type = str(normalized_image_payload.get("media_type") or "image/jpeg")
    trace_id = _read_optional_trace_id(request)

    def run_slice(window: _SliceWindow) -> list[dict[str, object]]:
        crop_image = source_image[window.y1 : window.y2, window.x1 : window.x2]
        crop_media_type, crop_image_bytes = _encode_slice_image(
            crop_image=crop_image,
            preferred_media_type=preferred_media_type,
        )
        slice_extra_options = dict(extra_options)
        slice_extra_options.setdefault("sahi_slice_index", window.index)
        slice_extra_options.setdefault("sahi_slice_bbox_xyxy", [window.x1, window.y1, window.x2, window.y2])
        slice_extra_options.setdefault("sahi_source_image_size", [image_width, image_height])
        inference_result = gateway.infer(
            PublishedInferenceRequest(
                deployment_instance_id=deployment_instance_id,
                image_payload={
                    "transport_kind": "memory",
                    "image_handle": _build_slice_image_handle(window),
                    "media_type": crop_media_type,
                    "width": window.width,
                    "height": window.height,
                },
                input_image_bytes=crop_image_bytes,
                auto_start_process=True if auto_start_process is None else auto_start_process,
                runtime_mode="sync",
                score_threshold=score_threshold,
                save_result_image=False if save_result_image is None else save_result_image,
                return_preview_image_base64=False
                if return_preview_image_base64 is None
                else return_preview_image_base64,
                extra_options=slice_extra_options,
                trace_id=trace_id,
            )
        )
        return _translate_slice_detections(
            inference_result.detections,
            offset_x=window.x1,
            offset_y=window.y1,
            image_width=image_width,
            image_height=image_height,
        )

    translated_items: list[dict[str, object]] = []
    if thread_workers <= 1 or len(slice_windows) <= 1:
        for window in slice_windows:
            translated_items.extend(run_slice(window))
    else:
        with ThreadPoolExecutor(max_workers=thread_workers) as executor:
            for slice_items in executor.map(run_slice, slice_windows):
                translated_items.extend(slice_items)

    merged_items = _merge_detection_items(
        translated_items,
        merge_mode=merge_mode,
        iou_threshold=normalized_iou_threshold,
    )
    return {"detections": {"items": merged_items}}


def _resolve_thread_workers(request: WorkflowNodeExecutionRequest) -> int:
    """读取并校验线程数参数。"""

    value = get_optional_int_parameter(request, "thread_workers")
    if value is None:
        return _DEFAULT_THREAD_WORKERS
    if value < 1:
        raise InvalidRequestError(
            "参数 thread_workers 必须大于等于 1",
            details={"node_id": request.node_id, "parameter": "thread_workers"},
        )
    return value


def _resolve_merge_mode(request: WorkflowNodeExecutionRequest) -> str:
    """读取并校验合并模式。"""

    value = get_optional_str_parameter(request, "merge_mode")
    normalized_value = (value or _MERGE_MODE_NMS).strip().lower()
    if normalized_value not in _SUPPORTED_MERGE_MODES:
        raise InvalidRequestError(
            "参数 merge_mode 仅支持 nms、nmm 或 none",
            details={"node_id": request.node_id, "parameter": "merge_mode", "value": value},
        )
    return normalized_value


def _normalize_iou_threshold(value: float | None) -> float:
    """规范化 IoU 阈值。"""

    normalized_value = _DEFAULT_IOU_THRESHOLD if value is None else float(value)
    if normalized_value < 0 or normalized_value > 1:
        raise InvalidRequestError(
            "参数 iou_threshold 必须位于 0 到 1 之间",
            details={"parameter": "iou_threshold", "value": value},
        )
    return normalized_value


def _resolve_slice_size(request: WorkflowNodeExecutionRequest) -> tuple[int, int]:
    """解析切片尺寸参数。"""

    slice_pair = get_optional_int_pair_parameter(request, "slice_wh")
    if slice_pair is not None:
        slice_width, slice_height = slice_pair
    else:
        slice_width = get_optional_int_parameter(request, "slice_width") or _DEFAULT_SLICE_WIDTH
        slice_height = get_optional_int_parameter(request, "slice_height") or _DEFAULT_SLICE_HEIGHT
    if slice_width < 1 or slice_height < 1:
        raise InvalidRequestError(
            "切片尺寸必须大于等于 1",
            details={"slice_width": slice_width, "slice_height": slice_height},
        )
    return slice_width, slice_height


def _resolve_overlap_size(
    request: WorkflowNodeExecutionRequest,
    *,
    slice_width: int,
    slice_height: int,
) -> tuple[int, int]:
    """解析重叠尺寸参数。"""

    overlap_pair = get_optional_int_pair_parameter(request, "overlap_wh")
    if overlap_pair is not None:
        overlap_width, overlap_height = overlap_pair
    else:
        overlap_width = get_optional_int_parameter(request, "overlap_width")
        overlap_height = get_optional_int_parameter(request, "overlap_height")
        overlap_width = _DEFAULT_OVERLAP_WIDTH if overlap_width is None else overlap_width
        overlap_height = _DEFAULT_OVERLAP_HEIGHT if overlap_height is None else overlap_height
    if overlap_width < 0 or overlap_height < 0:
        raise InvalidRequestError(
            "重叠尺寸不能为负数",
            details={"overlap_width": overlap_width, "overlap_height": overlap_height},
        )
    if overlap_width >= slice_width or overlap_height >= slice_height:
        raise InvalidRequestError(
            "重叠尺寸必须小于切片尺寸",
            details={
                "slice_width": slice_width,
                "slice_height": slice_height,
                "overlap_width": overlap_width,
                "overlap_height": overlap_height,
            },
        )
    return overlap_width, overlap_height


def _decode_source_image(source_image_bytes: bytes):
    """把输入图片字节解码成 OpenCV BGR 图像。"""

    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - 运行环境缺依赖时由导入冒烟兜底
        raise InvalidRequestError("SAHI 节点缺少 OpenCV 或 NumPy 运行时依赖") from exc

    image_buffer = np.frombuffer(source_image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError("输入图片不是可读取的有效图像内容")
    return image


def _build_slice_windows(
    *,
    image_width: int,
    image_height: int,
    slice_width: int,
    slice_height: int,
    overlap_width: int,
    overlap_height: int,
) -> tuple[_SliceWindow, ...]:
    """按网格覆盖规则生成全部切片窗口。"""

    normalized_slice_width = min(slice_width, image_width)
    normalized_slice_height = min(slice_height, image_height)
    x_starts = _build_axis_starts(
        total_size=image_width,
        window_size=normalized_slice_width,
        overlap_size=overlap_width,
    )
    y_starts = _build_axis_starts(
        total_size=image_height,
        window_size=normalized_slice_height,
        overlap_size=overlap_height,
    )
    windows: list[_SliceWindow] = []
    window_index = 0
    for y1 in y_starts:
        for x1 in x_starts:
            x2 = min(image_width, x1 + normalized_slice_width)
            y2 = min(image_height, y1 + normalized_slice_height)
            windows.append(
                _SliceWindow(
                    index=window_index,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )
            window_index += 1
    return tuple(windows)


def _build_axis_starts(*, total_size: int, window_size: int, overlap_size: int) -> tuple[int, ...]:
    """按最后一片贴边规则生成单轴切片起点。"""

    if total_size <= window_size:
        return (0,)
    step_size = max(1, window_size - overlap_size)
    starts: list[int] = []
    current_start = 0
    while True:
        max_start = max(0, total_size - window_size)
        normalized_start = min(current_start, max_start)
        if not starts or normalized_start != starts[-1]:
            starts.append(normalized_start)
        if normalized_start >= max_start:
            break
        current_start += step_size
    return tuple(starts)


def _encode_slice_image(*, crop_image, preferred_media_type: str) -> tuple[str, bytes]:
    """把切片图像编码为可发送给 deployment gateway 的图片字节。"""

    import cv2  # noqa: PLC0415

    normalized_media_type = preferred_media_type.strip().lower()
    if normalized_media_type == "image/png":
        suffix = ".png"
        media_type = "image/png"
    elif normalized_media_type == "image/webp":
        suffix = ".webp"
        media_type = "image/webp"
    elif normalized_media_type == "image/bmp":
        suffix = ".bmp"
        media_type = "image/bmp"
    else:
        suffix = ".jpg"
        media_type = "image/jpeg"
    success, encoded = cv2.imencode(suffix, crop_image)
    if success is not True:
        raise InvalidRequestError("切片图片编码失败")
    return media_type, bytes(encoded.tobytes())


def _build_slice_image_handle(window: _SliceWindow) -> str:
    """构造切片调用使用的临时 image_handle。"""

    return f"sahi-slice-{window.index}-{next(_SLICE_IMAGE_HANDLE_COUNTER)}"


def _translate_slice_detections(
    raw_detections: Iterable[dict[str, object]],
    *,
    offset_x: int,
    offset_y: int,
    image_width: int,
    image_height: int,
) -> list[dict[str, object]]:
    """把切片内检测框平移回原图坐标系。"""

    translated_items: list[dict[str, object]] = []
    for raw_item in raw_detections:
        if not isinstance(raw_item, dict):
            continue
        raw_bbox = raw_item.get("bbox_xyxy")
        normalized_bbox = _normalize_bbox_xyxy(raw_bbox)
        if normalized_bbox is None:
            continue
        translated_bbox = [
            _clamp_coordinate(normalized_bbox[0] + offset_x, 0, image_width),
            _clamp_coordinate(normalized_bbox[1] + offset_y, 0, image_height),
            _clamp_coordinate(normalized_bbox[2] + offset_x, 0, image_width),
            _clamp_coordinate(normalized_bbox[3] + offset_y, 0, image_height),
        ]
        translated_item = {str(key): value for key, value in raw_item.items()}
        translated_item["bbox_xyxy"] = translated_bbox
        translated_items.append(translated_item)
    return translated_items


def _merge_detection_items(
    items: list[dict[str, object]],
    *,
    merge_mode: str,
    iou_threshold: float,
) -> list[dict[str, object]]:
    """按指定模式合并切片 detection 结果。"""

    sorted_items = sorted(items, key=_read_detection_sort_key, reverse=True)
    if merge_mode == _MERGE_MODE_NONE:
        return sorted_items
    if merge_mode == _MERGE_MODE_NMS:
        return _apply_detection_nms(sorted_items, iou_threshold=iou_threshold)
    return _apply_detection_nmm(sorted_items, iou_threshold=iou_threshold)


def _apply_detection_nms(items: list[dict[str, object]], *, iou_threshold: float) -> list[dict[str, object]]:
    """执行同类 detection 的 NMS 去重。"""

    kept_items: list[dict[str, object]] = []
    for current_item in items:
        current_bbox = _normalize_bbox_xyxy(current_item.get("bbox_xyxy"))
        if current_bbox is None:
            continue
        current_class_key = _read_detection_class_key(current_item)
        should_keep = True
        for kept_item in kept_items:
            kept_bbox = _normalize_bbox_xyxy(kept_item.get("bbox_xyxy"))
            if kept_bbox is None:
                continue
            if current_class_key != _read_detection_class_key(kept_item):
                continue
            if _compute_bbox_iou(current_bbox, kept_bbox) > iou_threshold:
                should_keep = False
                break
        if should_keep:
            kept_items.append(current_item)
    return kept_items


def _apply_detection_nmm(items: list[dict[str, object]], *, iou_threshold: float) -> list[dict[str, object]]:
    """执行同类 detection 的简单合并。"""

    merged_items: list[dict[str, object]] = []
    for current_item in items:
        current_bbox = _normalize_bbox_xyxy(current_item.get("bbox_xyxy"))
        if current_bbox is None:
            continue
        current_class_key = _read_detection_class_key(current_item)
        merged = False
        for merged_index, merged_item in enumerate(merged_items):
            merged_bbox = _normalize_bbox_xyxy(merged_item.get("bbox_xyxy"))
            if merged_bbox is None:
                continue
            if current_class_key != _read_detection_class_key(merged_item):
                continue
            if _compute_bbox_iou(current_bbox, merged_bbox) <= iou_threshold:
                continue
            merged_items[merged_index] = _merge_two_detection_items(merged_item, current_item)
            merged = True
            break
        if not merged:
            merged_items.append(current_item)
    return sorted(merged_items, key=_read_detection_sort_key, reverse=True)


def _merge_two_detection_items(left_item: dict[str, object], right_item: dict[str, object]) -> dict[str, object]:
    """按分数加权合并两条 detection。"""

    left_bbox = _normalize_bbox_xyxy(left_item.get("bbox_xyxy")) or [0.0, 0.0, 0.0, 0.0]
    right_bbox = _normalize_bbox_xyxy(right_item.get("bbox_xyxy")) or [0.0, 0.0, 0.0, 0.0]
    left_score = _read_detection_score(left_item)
    right_score = _read_detection_score(right_item)
    score_sum = max(left_score + right_score, 1e-6)
    merged_bbox = [
        ((left_bbox[index] * left_score) + (right_bbox[index] * right_score)) / score_sum
        for index in range(4)
    ]
    winner_item = left_item if left_score >= right_score else right_item
    merged_item = {str(key): value for key, value in winner_item.items()}
    merged_item["bbox_xyxy"] = merged_bbox
    merged_item["score"] = max(left_score, right_score)
    return merged_item


def _read_detection_sort_key(item: dict[str, object]) -> float:
    """读取 detection 排序键。"""

    return _read_detection_score(item)


def _read_detection_score(item: dict[str, object]) -> float:
    """读取 detection score。"""

    value = item.get("score")
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _read_detection_class_key(item: dict[str, object]) -> tuple[str, object]:
    """读取 detection 分类键。"""

    class_id = item.get("class_id")
    if isinstance(class_id, int) and not isinstance(class_id, bool):
        return ("class_id", class_id)
    class_name = item.get("class_name")
    if isinstance(class_name, str) and class_name.strip():
        return ("class_name", class_name.strip())
    return ("unknown", "")


def _normalize_bbox_xyxy(value: object) -> list[float] | None:
    """把 bbox 值规范化为长度为 4 的浮点数组。"""

    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    normalized_bbox: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        normalized_bbox.append(float(item))
    if normalized_bbox[2] <= normalized_bbox[0] or normalized_bbox[3] <= normalized_bbox[1]:
        return None
    return normalized_bbox


def _compute_bbox_iou(left_bbox: list[float], right_bbox: list[float]) -> float:
    """计算两个 bbox 的 IoU。"""

    inter_x1 = max(left_bbox[0], right_bbox[0])
    inter_y1 = max(left_bbox[1], right_bbox[1])
    inter_x2 = min(left_bbox[2], right_bbox[2])
    inter_y2 = min(left_bbox[3], right_bbox[3])
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    left_area = (left_bbox[2] - left_bbox[0]) * (left_bbox[3] - left_bbox[1])
    right_area = (right_bbox[2] - right_bbox[0]) * (right_bbox[3] - right_bbox[1])
    union_area = left_area + right_area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def _clamp_coordinate(value: float, lower_bound: int, upper_bound: int) -> float:
    """把坐标限制到原图边界内。"""

    if value < lower_bound:
        return float(lower_bound)
    if value > upper_bound:
        return float(upper_bound)
    return float(value)


def _read_optional_trace_id(request: WorkflowNodeExecutionRequest) -> str | None:
    """从执行元数据中读取可选 trace_id。"""

    trace_id = request.execution_metadata.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    workflow_run_id = request.execution_metadata.get("workflow_run_id")
    if isinstance(workflow_run_id, str) and workflow_run_id.strip():
        return workflow_run_id.strip()
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.model.sahi-inference",
        display_name="SAHI Inference",
        category="model.inference",
        description="按切片方式调用已发布 detection deployment，并合并大图检测结果。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
            NodePortDefinition(
                name="dependency",
                display_name="Dependency",
                payload_type_id="response-body.v1",
                required=False,
            ),
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "deployment_instance_id": {"type": "string"},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "slice_width": {"type": "integer", "minimum": 1},
                "slice_height": {"type": "integer", "minimum": 1},
                "slice_wh": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer", "minimum": 1},
                },
                "overlap_width": {"type": "integer", "minimum": 0},
                "overlap_height": {"type": "integer", "minimum": 0},
                "overlap_wh": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer", "minimum": 0},
                },
                "iou_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "merge_mode": {"type": "string", "enum": ["nms", "nmm", "none"]},
                "thread_workers": {"type": "integer", "minimum": 1},
                "auto_start_process": {"type": "boolean"},
                "save_result_image": {"type": "boolean"},
                "return_preview_image_base64": {"type": "boolean"},
                "extra_options": {"type": "object"},
            },
            "required": ["deployment_instance_id"],
        },
        capability_tags=("model.inference", "detection.sahi"),
        runtime_requirements={"deployment_process": "sync"},
    ),
    handler=_sahi_inference_handler,
)
