"""YOLO 主线导出构建计划。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.service.application.models.yolo_core_common.export.segmentation import (
    resolve_segmentation_export_output_names,
)


YOLO_EXPORT_INPUT_NAMES = ("images",)
YOLO_EXPORT_OPSET_VERSION = 17
YOLO_EXPORTER_MODE = "legacy-torch-onnx-export"
YOLO_EXPORT_TARGET_FORMATS = (
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
)
YOLO_EXPORT_PRECISION_METADATA_KEYS = {
    "openvino-ir": "openvino_ir_precision",
    "tensorrt-engine": "tensorrt_engine_precision",
}


@dataclass(frozen=True)
class YoloExportTargetSpec:
    """单个导出目标的构建信息。"""

    target_format: str
    step_kind: str
    source_format: str | None
    object_suffix: str
    precision_metadata_key: str | None = None


@dataclass(frozen=True)
class YoloExportTaskPlan:
    """某个 task_type 的 YOLO 导出计划。"""

    task_type: str
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    onnx_opset_version: int
    exporter_mode: str
    export_mode_enabled: bool
    target_specs: tuple[YoloExportTargetSpec, ...]

    def to_metadata(self) -> dict[str, object]:
        """返回可写入转换结果的导出计划摘要。"""

        return {
            "task_type": self.task_type,
            "input_names": list(self.input_names),
            "output_names": list(self.output_names),
            "onnx_opset_version": self.onnx_opset_version,
            "exporter_mode": self.exporter_mode,
            "export_mode_enabled": self.export_mode_enabled,
            "target_specs": [
                {
                    "target_format": spec.target_format,
                    "step_kind": spec.step_kind,
                    "source_format": spec.source_format,
                    "object_suffix": spec.object_suffix,
                    "precision_metadata_key": spec.precision_metadata_key,
                }
                for spec in self.target_specs
            ],
        }


def build_yolo_export_task_plan(
    *,
    task_type: str,
    target_formats: Iterable[str] = YOLO_EXPORT_TARGET_FORMATS,
) -> YoloExportTaskPlan:
    """按 task_type 和目标格式生成 YOLO 导出计划。"""

    output_names = resolve_yolo_export_output_names(task_type=task_type)
    return YoloExportTaskPlan(
        task_type=task_type,
        input_names=YOLO_EXPORT_INPUT_NAMES,
        output_names=output_names,
        onnx_opset_version=YOLO_EXPORT_OPSET_VERSION,
        exporter_mode=YOLO_EXPORTER_MODE,
        export_mode_enabled=is_yolo_export_mode_enabled(task_type=task_type),
        target_specs=resolve_yolo_export_target_specs(target_formats=target_formats),
    )


def resolve_yolo_export_output_names(*, task_type: str) -> tuple[str, ...]:
    """返回 YOLO 导出输出名。"""

    if task_type == "segmentation":
        return resolve_segmentation_export_output_names()
    if task_type == "classification":
        return ("probabilities",)
    return ("predictions",)


def is_yolo_export_mode_enabled(*, task_type: str) -> bool:
    """返回当前任务导出时是否需要打开模型 export 模式。"""

    return task_type == "classification"


def resolve_yolo_export_target_specs(
    *,
    target_formats: Iterable[str],
) -> tuple[YoloExportTargetSpec, ...]:
    """按目标格式返回有序构建步骤信息。"""

    requested_formats = tuple(str(item) for item in target_formats)
    specs: list[YoloExportTargetSpec] = []
    if "onnx" in requested_formats:
        specs.append(
            YoloExportTargetSpec(
                target_format="onnx",
                step_kind="export-onnx",
                source_format=None,
                object_suffix=".onnx",
            )
        )
    if "onnx-optimized" in requested_formats:
        specs.append(
            YoloExportTargetSpec(
                target_format="onnx-optimized",
                step_kind="optimize-onnx",
                source_format="onnx",
                object_suffix=".optimized.onnx",
            )
        )
    if "openvino-ir" in requested_formats:
        specs.append(
            YoloExportTargetSpec(
                target_format="openvino-ir",
                step_kind="build-openvino-ir",
                source_format="onnx-optimized",
                object_suffix=".openvino.xml",
                precision_metadata_key=YOLO_EXPORT_PRECISION_METADATA_KEYS["openvino-ir"],
            )
        )
    if "tensorrt-engine" in requested_formats:
        specs.append(
            YoloExportTargetSpec(
                target_format="tensorrt-engine",
                step_kind="build-tensorrt-engine",
                source_format="onnx-optimized",
                object_suffix=".tensorrt.engine",
                precision_metadata_key=YOLO_EXPORT_PRECISION_METADATA_KEYS["tensorrt-engine"],
            )
        )
    return tuple(specs)
