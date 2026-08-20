"""RF-DETR core 导出处理模块：`export.execution`。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.domain.models.model_input_spec import serialize_spatial_size_hw

import torch

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.models.rfdetr_core.export._onnx import (
    resolve_rfdetr_onnx_output_names,
)
from backend.service.application.models.rfdetr_core.export._onnx.exporter import (
    export_onnx as export_rfdetr_onnx,
)
from backend.service.application.models.rfdetr_core.export._tensorrt import (
    build_tensorrt_engine as build_rfdetr_tensorrt_engine,
)
from backend.service.application.models.rfdetr_core.export.validation import (
    build_rfdetr_dummy_input,
    validate_rfdetr_onnx,
)
from backend.service.application.models.rfdetr_core.factory import (
    align_rfdetr_full_core_input_size,
    build_rfdetr_full_core_model,
    resolve_rfdetr_full_core_input_divisor,
)
from backend.service.application.models.rfdetr_core.models.weights import (
    load_rfdetr_checkpoint_state_dict,
    load_rfdetr_deployment_weights,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)

RFDETR_ONNX_OPSET_VERSION = 18
RFDETR_ONNX_EXPORTER_MODE = "torch-onnx-dynamo-export"
RFDETR_DEFAULT_EXPORT_INPUT_SIZE = (384, 384)
RFDETR_EXPORT_TASK_TYPES = frozenset({DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE})


@dataclass(frozen=True)
class RfdetrExportContext:
    """RF-DETR core 类：`RfdetrExportContext`。"""

    task_type: str
    model_scale: str
    model: Any
    dummy_input: torch.Tensor
    output_names: tuple[str, ...]
    input_size_summary: dict[str, object]

    def close(self) -> None:
        """释放一次性导出模型和 dummy tensor，避免转换任务间保留大对象。"""

        model = self.model
        close_model = getattr(model, "close", None)
        if callable(close_model):
            close_model()
        object.__setattr__(self, "model", None)
        object.__setattr__(self, "dummy_input", None)
        del model


def prepare_rfdetr_export_context(
    *,
    checkpoint_path: Path | None,
    task_type: ModelTaskType,
    model_scale: str | None,
    num_classes: int,
    input_size: object,
) -> RfdetrExportContext:
    """执行 `prepare_rfdetr_export_context`。

    参数：
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `input_size`：传入的 `input_size` 参数。

    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = normalize_rfdetr_export_task_type(task_type)
    normalized_model_scale = (model_scale or "nano").strip().lower() or "nano"
    if checkpoint_path is None or not checkpoint_path.is_file():
        raise ServiceError("RF-DETR 转换缺少可读取的 checkpoint 文件")

    requested_input_size = resolve_rfdetr_export_input_size(input_size)
    (input_height, input_width), input_size_summary = (
        resolve_rfdetr_export_input_size_summary(
            task_type=normalized_task_type,
            model_scale=normalized_model_scale,
            input_size=requested_input_size,
        )
    )
    model = build_rfdetr_full_core_model(
        task_type=normalized_task_type,
        model_scale=normalized_model_scale,
        num_classes=num_classes,
        input_size=(input_height, input_width),
        load_pretrained=False,
    )
    try:
        load_rfdetr_deployment_weights(
            model=model,
            checkpoint_path=checkpoint_path,
        )
        model.to("cpu")
        model.eval()
        dummy_input = build_rfdetr_dummy_input(
            input_height=input_height,
            input_width=input_width,
        )
        return RfdetrExportContext(
            task_type=normalized_task_type,
            model_scale=normalized_model_scale,
            model=model,
            dummy_input=dummy_input,
            output_names=resolve_rfdetr_onnx_output_names(normalized_task_type),
            input_size_summary=input_size_summary,
        )
    except Exception:
        from backend.service.application.support.resource_cleanup import (
            release_model_task_resources,
        )

        release_model_task_resources(model)
        raise


def normalize_rfdetr_export_task_type(task_type: ModelTaskType) -> str:
    """执行 `normalize_rfdetr_export_task_type`。

    参数：
    - `task_type`：传入的 `task_type` 参数。

    返回：
    - 当前函数的执行结果。
    """

    normalized_task_type = str(task_type).strip().lower()
    if normalized_task_type in RFDETR_EXPORT_TASK_TYPES:
        return normalized_task_type
    raise InvalidRequestError(
        "RF-DETR 当前不支持指定任务分类的转换执行",
        details={"task_type": normalized_task_type},
    )


def load_rfdetr_export_state_dict(checkpoint_path: Path) -> dict[str, object]:
    """读取 RF-DETR 转换使用的部署权重。

    参数：
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。

    返回：
    - 当前函数的执行结果。
    """

    try:
        return dict(load_rfdetr_checkpoint_state_dict(checkpoint_path))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ServiceConfigurationError(
            "RF-DETR checkpoint 格式不包含可加载的部署权重",
            details={"checkpoint_path": str(checkpoint_path)},
        ) from exc


def resolve_rfdetr_export_input_size(input_size: object) -> tuple[int, int]:
    """执行 `resolve_rfdetr_export_input_size`。

    参数：
    - `input_size`：传入的 `input_size` 参数。

    返回：
    - 当前函数的执行结果。
    """

    if isinstance(input_size, Sequence) and not isinstance(input_size, str | bytes):
        if len(input_size) == 2:
            return int(input_size[0]), int(input_size[1])
    return RFDETR_DEFAULT_EXPORT_INPUT_SIZE


def resolve_rfdetr_export_input_size_summary(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    input_size: tuple[int, int],
) -> tuple[tuple[int, int], dict[str, object]]:
    """执行 `resolve_rfdetr_export_input_size_summary`。

    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `input_size`：传入的 `input_size` 参数。

    返回：
    - 当前函数的执行结果。
    """

    divisor = resolve_rfdetr_full_core_input_divisor(
        task_type=task_type,
        model_scale=model_scale,
    )
    try:
        aligned_input_size = align_rfdetr_full_core_input_size(
            task_type=task_type,
            model_scale=model_scale,
            input_size=input_size,
        )
    except ValueError as exc:
        raise InvalidRequestError(
            "RF-DETR full-core 转换输入尺寸必须大于 0",
            details={
                "task_type": str(task_type),
                "model_scale": model_scale,
                "input_size": serialize_spatial_size_hw(input_size),
                "required_divisor": divisor,
            },
        ) from exc
    if aligned_input_size != input_size:
        raise InvalidRequestError(
            "RF-DETR full-core 转换输入尺寸必须满足模型 divisor，禁止静默对齐",
            details={
                "task_type": str(task_type),
                "model_scale": model_scale,
                "input_size": serialize_spatial_size_hw(input_size),
                "required_divisor": divisor,
                "nearest_aligned_input_size": serialize_spatial_size_hw(
                    aligned_input_size
                ),
            },
        )
    return input_size, {
        "requested": serialize_spatial_size_hw(input_size),
        "effective": serialize_spatial_size_hw(input_size),
        "required_divisor": divisor,
    }


def import_rfdetr_onnx_conversion_dependencies() -> tuple[object, object, object]:
    """执行 `import_rfdetr_onnx_conversion_dependencies`。

    返回：
    - 当前函数的执行结果。
    """

    try:
        import onnx
        import onnxruntime
        from onnxsim import simplify
    except ImportError as error:
        raise ServiceConfigurationError("当前环境缺少 RF-DETR ONNX 转换依赖") from error
    return onnx, onnxruntime, simplify


def export_rfdetr_onnx_artifact(
    *,
    model: Any,
    dummy_input: torch.Tensor,
    output_path: Path,
    output_object_key: str,
    output_names: tuple[str, ...],
) -> dict[str, object]:
    """执行 `export_rfdetr_onnx_artifact`。

    参数：
    - `model`：传入的 `model` 参数。
    - `dummy_input`：传入的 `dummy_input` 参数。
    - `output_path`：传入的 `output_path` 参数。
    - `output_object_key`：传入的 `output_object_key` 参数。
    - `output_names`：传入的 `output_names` 参数。

    返回：
    - 当前函数的执行结果。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    exported_path = export_rfdetr_onnx(
        output_dir=str(output_path.parent),
        model=model,
        input_names=("image",),
        input_tensors=dummy_input,
        output_names=output_names,
        dynamic_axes=None,
        verbose=False,
        opset_version=RFDETR_ONNX_OPSET_VERSION,
        variant_name=output_path.stem,
    )
    if Path(exported_path).resolve() != output_path.resolve():
        raise ServiceConfigurationError(
            "RF-DETR ONNX 导出路径与任务产物路径不一致",
            details={
                "expected_path": str(output_path),
                "exported_path": str(exported_path),
            },
        )
    return {
        "stage": "export-onnx",
        "object_uri": output_object_key,
        "exported_path": str(exported_path),
        "opset_version": RFDETR_ONNX_OPSET_VERSION,
        "input_size": serialize_spatial_size_hw(
            (int(dummy_input.shape[-2]), int(dummy_input.shape[-1]))
        ),
        "input_tensor": {
            "name": "image",
            "layout": "NCHW",
            "shape": [int(value) for value in dummy_input.shape],
            "dtype": "float32",
        },
        "exporter_mode": RFDETR_ONNX_EXPORTER_MODE,
        "output_names": list(output_names),
    }


def validate_rfdetr_onnx_artifact(
    *,
    model: Any,
    dummy_input: torch.Tensor,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    output_names: tuple[str, ...],
) -> dict[str, object]:
    """执行 `validate_rfdetr_onnx_artifact`。

    参数：
    - `model`：传入的 `model` 参数。
    - `dummy_input`：传入的 `dummy_input` 参数。
    - `onnx_path`：传入的 `onnx_path` 参数。
    - `onnx_module`：传入的 `onnx_module` 参数。
    - `onnxruntime_module`：传入的 `onnxruntime_module` 参数。
    - `output_names`：传入的 `output_names` 参数。

    返回：
    - 当前函数的执行结果。
    """

    return validate_rfdetr_onnx(
        model=model,
        dummy_input=dummy_input,
        onnx_path=onnx_path,
        onnx_module=onnx_module,
        onnxruntime_module=onnxruntime_module,
        output_names=output_names,
    )


def build_rfdetr_tensorrt_engine_artifact(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
) -> dict[str, object]:
    """执行 `build_rfdetr_tensorrt_engine_artifact`。

    参数：
    - `source_path`：传入的 `source_path` 参数。
    - `output_path`：传入的 `output_path` 参数。
    - `source_object_key`：传入的 `source_object_key` 参数。
    - `output_object_key`：传入的 `output_object_key` 参数。
    - `build_precision`：传入的 `build_precision` 参数。

    返回：
    - 当前函数的执行结果。
    """

    build_summary = build_rfdetr_tensorrt_engine(
        onnx_path=source_path,
        engine_path=output_path,
        build_precision=build_precision,
    )
    if not output_path.is_file():
        raise ServiceConfigurationError(
            "RF-DETR TensorRT engine 构建未生成 engine 产物",
            details={"output_object_uri": output_object_key},
        )
    return {
        "stage": "build-tensorrt-engine",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "engine_file_bytes": output_path.stat().st_size,
        "input_dtype": "float32",
        **build_summary,
    }
