"""RF-DETR 转换规划器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.catalog.rfdetr import (
    RFDETR_MODEL_FILE_TYPES,
)
from backend.service.domain.files.detection_model_file_types import (
    DetectionModelFileTypes,
)
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_SUPPORTED_TASKS,
)

RfdetrConversionTarget = Literal[
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
]
RfdetrConversionStepKind = Literal[
    "export-onnx",
    "validate-onnx",
    "optimize-onnx",
    "build-openvino-ir",
    "build-tensorrt-engine",
]

_SUPPORTED_CONVERSION_TARGETS = frozenset({
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
})
_DOWNSTREAM_TARGETS_REQUIRING_OPTIMIZED_ONNX = frozenset({
    "openvino-ir",
    "tensorrt-engine",
})


@dataclass(frozen=True)
class RfdetrConversionPlanningRequest:
    """描述一次 RF-DETR 转换规划请求。"""

    project_id: str
    source_model_version_id: str
    target_formats: tuple[str, ...]
    task_type: str
    runtime_profile_id: str | None = None
    preferred_device: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RfdetrConversionStep:
    """描述 RF-DETR 转换计划中的单个步骤。"""

    kind: RfdetrConversionStepKind
    source_format: str
    target_format: str
    required_file_type: str
    produced_file_type: str | None = None


@dataclass(frozen=True)
class RfdetrConversionPlan:
    """描述一次 RF-DETR 转换执行计划。"""

    source_model_version_id: str
    target_formats: tuple[str, ...]
    steps: tuple[RfdetrConversionStep, ...]


class RfdetrConversionPlanner(Protocol):
    """根据平台对象生成 RF-DETR 转换执行计划。"""

    def build_plan(
        self,
        request: RfdetrConversionPlanningRequest,
    ) -> RfdetrConversionPlan:
        """构建 RF-DETR 转换计划。"""

        ...


class DefaultRfdetrConversionPlanner:
    """根据 RF-DETR build 图谱生成转换计划。"""

    model_type = "rfdetr"

    def __init__(
        self,
        *,
        file_types: DetectionModelFileTypes = RFDETR_MODEL_FILE_TYPES,
        supported_task_types: tuple[str, ...] = RFDETR_SUPPORTED_TASKS,
    ) -> None:
        """初始化 RF-DETR 转换规划器。"""

        self.file_types = file_types
        self.supported_task_types = tuple(
            item for item in supported_task_types if isinstance(item, str) and item.strip()
        )

    def build_plan(
        self,
        request: RfdetrConversionPlanningRequest,
    ) -> RfdetrConversionPlan:
        """构建 RF-DETR 转换执行计划。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.source_model_version_id.strip():
            raise InvalidRequestError("source_model_version_id 不能为空")
        if request.task_type not in self.supported_task_types:
            raise InvalidRequestError(
                "RF-DETR 当前不支持指定任务分类的转换规划",
                details={"task_type": request.task_type},
            )
        target_formats = _normalize_target_formats(request.target_formats)
        if not target_formats:
            raise InvalidRequestError("target_formats 不能为空")

        planned_steps: list[RfdetrConversionStep] = []
        if _requires_onnx_export(target_formats):
            planned_steps.append(
                RfdetrConversionStep(
                    kind="export-onnx",
                    source_format="pytorch-checkpoint",
                    target_format="onnx",
                    required_file_type=self.file_types.checkpoint_file_type,
                    produced_file_type=self.file_types.onnx_file_type,
                )
            )
            planned_steps.append(
                RfdetrConversionStep(
                    kind="validate-onnx",
                    source_format="onnx",
                    target_format="onnx",
                    required_file_type=self.file_types.onnx_file_type,
                    produced_file_type=None,
                )
            )

        if _requires_optimized_onnx(target_formats):
            planned_steps.append(
                RfdetrConversionStep(
                    kind="optimize-onnx",
                    source_format="onnx",
                    target_format="onnx-optimized",
                    required_file_type=self.file_types.onnx_file_type,
                    produced_file_type=self.file_types.onnx_optimized_file_type,
                )
            )

        if "openvino-ir" in target_formats:
            planned_steps.append(
                RfdetrConversionStep(
                    kind="build-openvino-ir",
                    source_format="onnx-optimized",
                    target_format="openvino-ir",
                    required_file_type=self.file_types.onnx_optimized_file_type,
                    produced_file_type=self.file_types.openvino_ir_file_type,
                )
            )

        if "tensorrt-engine" in target_formats:
            planned_steps.append(
                RfdetrConversionStep(
                    kind="build-tensorrt-engine",
                    source_format="onnx-optimized",
                    target_format="tensorrt-engine",
                    required_file_type=self.file_types.onnx_optimized_file_type,
                    produced_file_type=self.file_types.tensorrt_engine_file_type,
                )
            )

        return RfdetrConversionPlan(
            source_model_version_id=request.source_model_version_id,
            target_formats=target_formats,
            steps=tuple(planned_steps),
        )


def serialize_rfdetr_conversion_step(step: RfdetrConversionStep) -> dict[str, object]:
    """把 RF-DETR 转换步骤序列化为可持久化字典。"""

    return {
        "kind": step.kind,
        "source_format": step.source_format,
        "target_format": step.target_format,
        "required_file_type": step.required_file_type,
        "produced_file_type": step.produced_file_type,
    }


def deserialize_rfdetr_conversion_step(payload: dict[str, object]) -> RfdetrConversionStep:
    """从持久化字典恢复 RF-DETR 转换步骤。"""

    return RfdetrConversionStep(
        kind=_require_step_literal(payload, "kind"),
        source_format=_require_step_str(payload, "source_format"),
        target_format=_require_step_str(payload, "target_format"),
        required_file_type=_require_step_str(payload, "required_file_type"),
        produced_file_type=_read_optional_step_str(payload, "produced_file_type"),
    )


def serialize_rfdetr_conversion_plan(plan: RfdetrConversionPlan) -> dict[str, object]:
    """把 RF-DETR 转换计划序列化为可持久化字典。"""

    return {
        "source_model_version_id": plan.source_model_version_id,
        "target_formats": list(plan.target_formats),
        "steps": [serialize_rfdetr_conversion_step(item) for item in plan.steps],
    }


def deserialize_rfdetr_conversion_plan(payload: dict[str, object]) -> RfdetrConversionPlan:
    """从持久化字典恢复 RF-DETR 转换计划。"""

    raw_target_formats = payload.get("target_formats")
    if not isinstance(raw_target_formats, list):
        raise InvalidRequestError("RF-DETR 转换计划缺少 target_formats")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise InvalidRequestError("RF-DETR 转换计划缺少 steps")
    return RfdetrConversionPlan(
        source_model_version_id=_require_step_str(payload, "source_model_version_id"),
        target_formats=_normalize_target_formats(tuple(raw_target_formats)),
        steps=tuple(
            deserialize_rfdetr_conversion_step(item)
            for item in raw_steps
            if isinstance(item, dict)
        ),
    )


def _normalize_target_formats(
    target_formats: tuple[str, ...],
) -> tuple[RfdetrConversionTarget, ...]:
    """归一化 RF-DETR 转换目标列表，去重并保持原有顺序。"""

    normalized_items: list[RfdetrConversionTarget] = []
    seen: set[str] = set()
    for item in target_formats:
        if not isinstance(item, str):
            raise InvalidRequestError("target_formats 中存在非法目标格式")
        normalized_item = item.strip()
        if not normalized_item:
            continue
        if normalized_item not in _SUPPORTED_CONVERSION_TARGETS:
            raise InvalidRequestError(
                "RF-DETR target_formats 中存在不支持的目标格式",
                details={"target_format": normalized_item},
            )
        if normalized_item in seen:
            continue
        seen.add(normalized_item)
        normalized_items.append(normalized_item)
    return tuple(normalized_items)


def _requires_onnx_export(target_formats: tuple[RfdetrConversionTarget, ...]) -> bool:
    """判断当前目标集合是否需要先导出 ONNX。"""

    return bool(target_formats)


def _requires_optimized_onnx(
    target_formats: tuple[RfdetrConversionTarget, ...],
) -> bool:
    """判断当前目标集合是否需要先生成 optimized ONNX。"""

    return any(
        item == "onnx-optimized" or item in _DOWNSTREAM_TARGETS_REQUIRING_OPTIMIZED_ONNX
        for item in target_formats
    )


def _require_step_str(payload: dict[str, object], key: str) -> str:
    """从 RF-DETR 转换步骤载荷中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidRequestError("RF-DETR 转换步骤缺少必要字段", details={"field": key})


def _read_optional_step_str(payload: dict[str, object], key: str) -> str | None:
    """从 RF-DETR 转换步骤载荷中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_step_literal(
    payload: dict[str, object],
    key: str,
) -> RfdetrConversionStepKind:
    """从 RF-DETR 转换步骤载荷中读取必填步骤类型字段。"""

    value = _require_step_str(payload, key)
    if value not in {
        "export-onnx",
        "validate-onnx",
        "optimize-onnx",
        "build-openvino-ir",
        "build-tensorrt-engine",
    }:
        raise InvalidRequestError(
            "RF-DETR 转换步骤 kind 不受支持",
            details={"kind": value},
        )
    return value
