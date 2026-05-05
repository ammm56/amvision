"""YOLOX 转换规划接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_RKNN_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.domain.tasks.yolox_task_specs import YoloXConversionTarget


# 当前骨架支持的转换步骤类型。
YoloXConversionStepKind = Literal[
    "export-onnx",
    "validate-onnx",
    "optimize-onnx",
    "build-openvino-ir",
    "build-tensorrt-engine",
    "build-rknn",
]


@dataclass(frozen=True)
class YoloXConversionPlanningRequest:
    """描述一次转换规划请求。

    字段：
    - project_id：所属项目 id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标格式列表。
    - runtime_profile_id：目标 RuntimeProfile id。
    - preferred_device：优先使用的 device。
    - metadata：附加元数据。
    """

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloXConversionTarget, ...]
    runtime_profile_id: str | None = None
    preferred_device: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionStep:
    """描述转换计划中的单个步骤。

    字段：
    - kind：步骤类型。
    - source_format：来源格式。
    - target_format：目标格式。
    - required_file_type：执行该步骤需要的 file type。
    - produced_file_type：该步骤产出的 file type；纯校验步骤为空。
    """

    kind: YoloXConversionStepKind
    source_format: str
    target_format: str
    required_file_type: str
    produced_file_type: str | None = None


@dataclass(frozen=True)
class YoloXConversionPlan:
    """描述一次完整的转换执行计划。

    字段：
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标格式列表。
    - steps：计划中的转换步骤列表。
    """

    source_model_version_id: str
    target_formats: tuple[str, ...]
    steps: tuple[YoloXConversionStep, ...]


class YoloXConversionPlanner(Protocol):
    """根据平台对象生成 YOLOX 转换执行计划。"""

    def build_plan(self, request: YoloXConversionPlanningRequest) -> YoloXConversionPlan:
        """构建转换计划。

        参数：
        - request：转换规划请求。

        返回：
        - 转换执行计划。
        """

        ...


_SUPPORTED_CONVERSION_TARGETS = frozenset({
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
})
_DOWNSTREAM_TARGETS_REQUIRING_OPTIMIZED_ONNX = frozenset({
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
})


class DefaultYoloXConversionPlanner:
    """根据稳定 build 图谱生成 YOLOX 转换计划。"""

    def build_plan(self, request: YoloXConversionPlanningRequest) -> YoloXConversionPlan:
        """构建转换计划。

        参数：
        - request：转换规划请求。

        返回：
        - YoloXConversionPlan：稳定的转换执行计划。
        """

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.source_model_version_id.strip():
            raise InvalidRequestError("source_model_version_id 不能为空")
        target_formats = _normalize_target_formats(request.target_formats)
        if not target_formats:
            raise InvalidRequestError("target_formats 不能为空")

        planned_steps: list[YoloXConversionStep] = []
        if _requires_onnx_export(target_formats):
            planned_steps.append(
                YoloXConversionStep(
                    kind="export-onnx",
                    source_format="pytorch-checkpoint",
                    target_format="onnx",
                    required_file_type="yolox-checkpoint",
                    produced_file_type=YOLOX_ONNX_FILE,
                )
            )
            planned_steps.append(
                YoloXConversionStep(
                    kind="validate-onnx",
                    source_format="onnx",
                    target_format="onnx",
                    required_file_type=YOLOX_ONNX_FILE,
                    produced_file_type=None,
                )
            )

        if _requires_optimized_onnx(target_formats):
            planned_steps.append(
                YoloXConversionStep(
                    kind="optimize-onnx",
                    source_format="onnx",
                    target_format="onnx-optimized",
                    required_file_type=YOLOX_ONNX_FILE,
                    produced_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                )
            )

        if "openvino-ir" in target_formats:
            planned_steps.append(
                YoloXConversionStep(
                    kind="build-openvino-ir",
                    source_format="onnx-optimized",
                    target_format="openvino-ir",
                    required_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    produced_file_type=YOLOX_OPENVINO_IR_FILE,
                )
            )

        if "tensorrt-engine" in target_formats:
            planned_steps.append(
                YoloXConversionStep(
                    kind="build-tensorrt-engine",
                    source_format="onnx-optimized",
                    target_format="tensorrt-engine",
                    required_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    produced_file_type=YOLOX_TENSORRT_ENGINE_FILE,
                )
            )

        if "rknn" in target_formats:
            planned_steps.append(
                YoloXConversionStep(
                    kind="build-rknn",
                    source_format="onnx-optimized",
                    target_format="rknn",
                    required_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    produced_file_type=YOLOX_RKNN_FILE,
                )
            )

        return YoloXConversionPlan(
            source_model_version_id=request.source_model_version_id,
            target_formats=target_formats,
            steps=tuple(planned_steps),
        )


def serialize_yolox_conversion_step(step: YoloXConversionStep) -> dict[str, object]:
    """把转换步骤序列化为可持久化字典。"""

    return {
        "kind": step.kind,
        "source_format": step.source_format,
        "target_format": step.target_format,
        "required_file_type": step.required_file_type,
        "produced_file_type": step.produced_file_type,
    }


def deserialize_yolox_conversion_step(payload: dict[str, object]) -> YoloXConversionStep:
    """从持久化字典恢复转换步骤。"""

    return YoloXConversionStep(
        kind=_require_step_literal(payload, "kind"),
        source_format=_require_step_str(payload, "source_format"),
        target_format=_require_step_str(payload, "target_format"),
        required_file_type=_require_step_str(payload, "required_file_type"),
        produced_file_type=_read_optional_step_str(payload, "produced_file_type"),
    )


def serialize_yolox_conversion_plan(plan: YoloXConversionPlan) -> dict[str, object]:
    """把转换计划序列化为可持久化字典。"""

    return {
        "source_model_version_id": plan.source_model_version_id,
        "target_formats": list(plan.target_formats),
        "steps": [serialize_yolox_conversion_step(item) for item in plan.steps],
    }


def deserialize_yolox_conversion_plan(payload: dict[str, object]) -> YoloXConversionPlan:
    """从持久化字典恢复转换计划。"""

    raw_target_formats = payload.get("target_formats")
    if not isinstance(raw_target_formats, list):
        raise InvalidRequestError("转换计划缺少 target_formats")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise InvalidRequestError("转换计划缺少 steps")
    return YoloXConversionPlan(
        source_model_version_id=_require_step_str(payload, "source_model_version_id"),
        target_formats=_normalize_target_formats(tuple(raw_target_formats)),
        steps=tuple(
            deserialize_yolox_conversion_step(item)
            for item in raw_steps
            if isinstance(item, dict)
        ),
    )


def _normalize_target_formats(target_formats: tuple[str, ...]) -> tuple[YoloXConversionTarget, ...]:
    """归一化转换目标列表，去重并保持原有顺序。"""

    normalized_items: list[YoloXConversionTarget] = []
    seen: set[str] = set()
    for item in target_formats:
        if not isinstance(item, str):
            raise InvalidRequestError("target_formats 中存在非法目标格式")
        normalized_item = item.strip()
        if not normalized_item:
            continue
        if normalized_item not in _SUPPORTED_CONVERSION_TARGETS:
            raise InvalidRequestError(
                "target_formats 中存在不支持的目标格式",
                details={"target_format": normalized_item},
            )
        if normalized_item in seen:
            continue
        seen.add(normalized_item)
        normalized_items.append(normalized_item)
    return tuple(normalized_items)


def _requires_onnx_export(target_formats: tuple[YoloXConversionTarget, ...]) -> bool:
    """判断当前目标集合是否需要先导出 ONNX。"""

    return bool(target_formats)


def _requires_optimized_onnx(target_formats: tuple[YoloXConversionTarget, ...]) -> bool:
    """判断当前目标集合是否需要先生成 optimized ONNX。"""

    return any(
        item == "onnx-optimized" or item in _DOWNSTREAM_TARGETS_REQUIRING_OPTIMIZED_ONNX
        for item in target_formats
    )


def _require_step_str(payload: dict[str, object], key: str) -> str:
    """从步骤载荷中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidRequestError("转换步骤缺少必要字段", details={"field": key})


def _read_optional_step_str(payload: dict[str, object], key: str) -> str | None:
    """从步骤载荷中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_step_literal(payload: dict[str, object], key: str) -> YoloXConversionStepKind:
    """从步骤载荷中读取必填步骤类型字段。"""

    value = _require_step_str(payload, key)
    if value not in {
        "export-onnx",
        "validate-onnx",
        "optimize-onnx",
        "build-openvino-ir",
        "build-tensorrt-engine",
        "build-rknn",
    }:
        raise InvalidRequestError("转换步骤 kind 不受支持", details={"kind": value})
    return value