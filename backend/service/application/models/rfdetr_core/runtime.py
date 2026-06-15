"""RF-DETR core 运行时语义模块：`runtime`。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.rfdetr_core.detection import (
    build_rfdetr_postprocess,
)
from backend.service.application.models.rfdetr_core.factory import (
    align_rfdetr_full_core_input_size,
)
from backend.service.application.models.rfdetr_core.segmentation import (
    build_rfdetr_segmentation_postprocess,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)

_DETECTION_INPUT_SIZES = {
    "nano": 384,
    "s": 512,
    "m": 576,
    "l": 704,
}
_SEGMENTATION_INPUT_SIZES = {
    "nano": 384,
    "s": 512,
    "m": 576,
    "l": 704,
    "x": 768,
}


def resolve_rfdetr_runtime_input_size(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    input_size: object,
) -> tuple[int, int]:
    """执行 `resolve_rfdetr_runtime_input_size`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `input_size`：传入的 `input_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = str(task_type).strip().lower()
    normalized_model_scale = str(model_scale or "nano").strip().lower() or "nano"
    requested_input_size = _read_runtime_input_size(
        input_size=input_size,
        task_type=normalized_task_type,
        model_scale=normalized_model_scale,
    )
    return align_rfdetr_full_core_input_size(
        task_type=normalized_task_type,
        model_scale=normalized_model_scale,
        input_size=requested_input_size,
    )


def build_rfdetr_runtime_postprocess_model(*, task_type: ModelTaskType) -> Any:
    """执行 `build_rfdetr_runtime_postprocess_model`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = str(task_type).strip().lower()
    if normalized_task_type == DETECTION_TASK_TYPE:
        return build_rfdetr_postprocess()
    if normalized_task_type == SEGMENTATION_TASK_TYPE:
        return build_rfdetr_segmentation_postprocess()
    raise ServiceConfigurationError(
        "RF-DETR runtime 后处理不支持指定任务分类",
        details={"task_type": normalized_task_type},
    )


def postprocess_rfdetr_runtime_outputs(
    *,
    torch_module: Any,
    postprocess_model: Any,
    raw_outputs: dict[str, Any],
    image_height: int,
    image_width: int,
) -> dict[str, Any]:
    """执行 `postprocess_rfdetr_runtime_outputs`。
    
    参数：
    - `torch_module`：传入的 `torch_module` 参数。
    - `postprocess_model`：传入的 `postprocess_model` 参数。
    - `raw_outputs`：传入的 `raw_outputs` 参数。
    - `image_height`：传入的 `image_height` 参数。
    - `image_width`：传入的 `image_width` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return postprocess_model.postprocess(
        {
            "pred_logits": _as_torch_tensor(
                torch_module=torch_module,
                value=raw_outputs["pred_logits"],
            ),
            "pred_boxes": _as_torch_tensor(
                torch_module=torch_module,
                value=raw_outputs["pred_boxes"],
            ),
        },
        torch_module.tensor(
            [[float(image_height), float(image_width)]],
            dtype=torch_module.float32,
        ),
    )


def postprocess_rfdetr_segmentation_runtime_outputs(
    *,
    torch_module: Any,
    postprocess_model: Any,
    raw_outputs: dict[str, Any],
    image_height: int,
    image_width: int,
) -> dict[str, Any]:
    """执行 `postprocess_rfdetr_segmentation_runtime_outputs`。
    
    参数：
    - `torch_module`：传入的 `torch_module` 参数。
    - `postprocess_model`：传入的 `postprocess_model` 参数。
    - `raw_outputs`：传入的 `raw_outputs` 参数。
    - `image_height`：传入的 `image_height` 参数。
    - `image_width`：传入的 `image_width` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return postprocess_model.postprocess(
        {
            "pred_logits": _as_torch_tensor(
                torch_module=torch_module,
                value=raw_outputs["pred_logits"],
            ),
            "pred_boxes": _as_torch_tensor(
                torch_module=torch_module,
                value=raw_outputs["pred_boxes"],
            ),
            "pred_masks": _as_torch_tensor(
                torch_module=torch_module,
                value=raw_outputs["pred_masks"],
            ),
        },
        torch_module.tensor(
            [[float(image_height), float(image_width)]],
            dtype=torch_module.float32,
        ),
    )


def build_rfdetr_single_channel_mask_array(
    *,
    mask_tensor: Any,
    mask_threshold: float,
) -> Any:
    """执行 `build_rfdetr_single_channel_mask_array`。
    
    参数：
    - `mask_tensor`：传入的 `mask_tensor` 参数。
    - `mask_threshold`：传入的 `mask_threshold` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_mask = mask_tensor.detach().cpu()
    while normalized_mask.ndim > 2 and int(normalized_mask.shape[0]) == 1:
        normalized_mask = normalized_mask.squeeze(0)
    while normalized_mask.ndim > 2 and int(normalized_mask.shape[-1]) == 1:
        normalized_mask = normalized_mask.squeeze(-1)
    if str(normalized_mask.dtype) == "torch.bool":
        binary_mask = normalized_mask.numpy().astype("uint8", copy=False)
    else:
        binary_mask = (
            (normalized_mask.sigmoid() >= mask_threshold)
            .numpy()
            .astype("uint8", copy=False)
        )
    if binary_mask.ndim != 2:
        raise ServiceConfigurationError(
            "RF-DETR segmentation mask 不是单通道二维数组",
            details={"mask_shape": list(binary_mask.shape)},
        )
    if not binary_mask.flags.c_contiguous:
        binary_mask = binary_mask.copy(order="C")
    return binary_mask


def resolve_rfdetr_runtime_output_names(
    *,
    task_type: ModelTaskType,
    output_names: tuple[str, ...],
) -> tuple[str, ...]:
    """执行 `resolve_rfdetr_runtime_output_names`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `output_names`：传入的 `output_names` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = str(task_type).strip().lower()
    if normalized_task_type == DETECTION_TASK_TYPE:
        return _resolve_preferred_output_names(
            output_names=output_names,
            preferred_names=("pred_logits", "pred_boxes"),
            error_message="RF-DETR 推理输出数量不足",
        )
    if normalized_task_type == SEGMENTATION_TASK_TYPE:
        return _resolve_preferred_output_names(
            output_names=output_names,
            preferred_names=("pred_logits", "pred_boxes", "pred_masks"),
            error_message="RF-DETR segmentation 推理输出数量不足",
        )
    raise ServiceConfigurationError(
        "RF-DETR runtime 输出名解析不支持指定任务分类",
        details={"task_type": normalized_task_type},
    )


def _read_runtime_input_size(
    *,
    input_size: object,
    task_type: str,
    model_scale: str,
) -> tuple[int, int]:
    """执行 `_read_runtime_input_size`。
    
    参数：
    - `input_size`：传入的 `input_size` 参数。
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if (
        isinstance(input_size, tuple)
        and len(input_size) == 2
        and int(input_size[0]) > 0
        and int(input_size[1]) > 0
    ):
        return int(input_size[0]), int(input_size[1])
    input_edge = _resolve_default_input_edge(
        task_type=task_type,
        model_scale=model_scale,
    )
    return input_edge, input_edge


def _resolve_default_input_edge(*, task_type: str, model_scale: str) -> int:
    """执行 `_resolve_default_input_edge`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if task_type == DETECTION_TASK_TYPE:
        return _DETECTION_INPUT_SIZES.get(model_scale, 384)
    if task_type == SEGMENTATION_TASK_TYPE:
        return _SEGMENTATION_INPUT_SIZES.get(model_scale, 384)
    raise ServiceConfigurationError(
        "RF-DETR runtime 输入尺寸不支持指定任务分类",
        details={"task_type": task_type},
    )


def _resolve_preferred_output_names(
    *,
    output_names: tuple[str, ...],
    preferred_names: tuple[str, ...],
    error_message: str,
) -> tuple[str, ...]:
    """按首选顺序解析输出名，不足时按原始顺序补齐。"""

    resolved_names: list[str] = []
    remaining_names = list(output_names)
    for preferred_name in preferred_names:
        if preferred_name in remaining_names:
            resolved_names.append(preferred_name)
            remaining_names.remove(preferred_name)
    if len(resolved_names) == len(preferred_names):
        return tuple(resolved_names)
    for output_name in output_names:
        if output_name not in resolved_names:
            resolved_names.append(output_name)
        if len(resolved_names) == len(preferred_names):
            return tuple(resolved_names)
    raise ServiceConfigurationError(
        error_message,
        details={"output_names": list(output_names)},
    )


def _as_torch_tensor(*, torch_module: Any, value: Any) -> Any:
    """执行 `_as_torch_tensor`。
    
    参数：
    - `torch_module`：传入的 `torch_module` 参数。
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if isinstance(value, torch_module.Tensor):
        return value.detach().cpu().float()
    return torch_module.from_numpy(value).float()
