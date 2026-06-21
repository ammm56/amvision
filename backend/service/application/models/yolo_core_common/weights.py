"""YOLO 主线共用权重覆盖率和加载边界。"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
import types
from typing import Any, Callable

from torch import nn

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.validation.model_core_validation import (
    StateDictCoverageSummary,
    analyze_state_dict_coverage,
)


YOLO_IGNORED_SOURCE_KEY_SUFFIXES = ("dfl.conv.weight",)
_PICKLE_CHECKPOINT_MODULE_NAMES = (
    "ultralytics",
    "ultralytics.nn",
    "ultralytics.nn.modules",
    "ultralytics.nn.modules.block",
    "ultralytics.nn.modules.conv",
    "ultralytics.nn.modules.head",
    "ultralytics.nn.tasks",
)
_MISSING_MODULE = object()


@dataclass(frozen=True)
class YoloStateDictLoadResult:
    """描述一次 YOLO state_dict 加载结果。"""

    coverage: StateDictCoverageSummary
    loaded_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    unexpected_keys: tuple[str, ...]
    shape_mismatch_keys: tuple[str, ...]
    checkpoint_path: str | None = None


def analyze_yolo_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> StateDictCoverageSummary:
    """按 YOLO 主线规则分析 source_state_dict 对目标模型的覆盖率。"""

    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        key_prefixes_to_strip=("model.", "module."),
        ignored_source_key_suffixes=YOLO_IGNORED_SOURCE_KEY_SUFFIXES,
    )


def load_yolo_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
    minimum_loadable_ratio: float = 1.0,
) -> YoloStateDictLoadResult:
    """加载 YOLO state_dict，并强制返回覆盖率报告。"""

    coverage = analyze_yolo_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )
    if coverage.loadable_ratio < float(minimum_loadable_ratio):
        raise ServiceConfigurationError(
            "YOLO state_dict 覆盖率低于要求",
            details={
                "minimum_loadable_ratio": float(minimum_loadable_ratio),
                "loadable_ratio": coverage.loadable_ratio,
                "missing_keys": list(coverage.missing_keys),
                "unexpected_keys": list(coverage.unexpected_keys),
                "shape_mismatch_keys": list(coverage.shape_mismatch_keys),
                "ignored_source_keys": list(coverage.ignored_source_keys),
            },
        )
    if coverage.shape_mismatch_keys:
        raise ServiceConfigurationError(
            "YOLO state_dict 存在 shape mismatch",
            details={"shape_mismatch_keys": list(coverage.shape_mismatch_keys)},
        )

    loadable_state_dict = _build_loadable_state_dict(
        model=model,
        source_state_dict=source_state_dict,
    )
    incompatible_keys = model.load_state_dict(loadable_state_dict, strict=False)
    return YoloStateDictLoadResult(
        coverage=coverage,
        loaded_keys=tuple(sorted(loadable_state_dict)),
        missing_keys=tuple(str(item) for item in incompatible_keys.missing_keys),
        unexpected_keys=tuple(str(item) for item in incompatible_keys.unexpected_keys),
        shape_mismatch_keys=coverage.shape_mismatch_keys,
    )


def load_yolo_checkpoint_file(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    minimum_loadable_ratio: float = 1.0,
    pickle_class_binders: tuple[Callable[..., None], ...] = (),
) -> YoloStateDictLoadResult:
    """读取 checkpoint 文件、提取 state_dict 并加载到 YOLO 模型。"""

    checkpoint_payload = load_yolo_checkpoint_payload(
        torch_module=torch_module,
        checkpoint_path=checkpoint_path,
        pickle_class_binders=pickle_class_binders,
    )
    source_state_dict = extract_yolo_checkpoint_state_dict(checkpoint_payload)
    load_result = load_yolo_state_dict(
        model=model,
        source_state_dict=source_state_dict,
        minimum_loadable_ratio=minimum_loadable_ratio,
    )
    return YoloStateDictLoadResult(
        coverage=load_result.coverage,
        loaded_keys=load_result.loaded_keys,
        missing_keys=load_result.missing_keys,
        unexpected_keys=load_result.unexpected_keys,
        shape_mismatch_keys=load_result.shape_mismatch_keys,
        checkpoint_path=str(checkpoint_path),
    )


def load_yolo_checkpoint_payload(
    *,
    torch_module: Any,
    checkpoint_path: Path,
    pickle_class_binders: tuple[Callable[..., None], ...] = (),
) -> object:
    """读取 YOLO checkpoint 原始载荷。

    优先使用 `weights_only=True` 读取纯权重文件；如果文件是完整模型 pickle，
    再降级到完整 pickle 读取。最后一步只临时注册旧模块路径，避免把外部包作为运行时依赖。
    """

    load_errors: list[str] = []
    for weights_only in (True, False):
        try:
            return torch_module.load(
                str(checkpoint_path),
                map_location="cpu",
                weights_only=weights_only,
            )
        except TypeError:
            try:
                return torch_module.load(str(checkpoint_path), map_location="cpu")
            except Exception as error:  # pragma: no cover - 仅在 checkpoint 不合法时进入
                load_errors.append(str(error))
        except Exception as error:
            load_errors.append(str(error))

    try:
        return _load_pickle_checkpoint_payload(
            torch_module=torch_module,
            checkpoint_path=checkpoint_path,
            pickle_class_binders=pickle_class_binders,
        )
    except Exception as error:
        load_errors.append(str(error))

    raise ServiceConfigurationError(
        "当前 YOLO checkpoint 无法加载为项目内模型权重",
        details={"checkpoint_path": str(checkpoint_path), "errors": load_errors},
    )


def extract_yolo_checkpoint_state_dict(checkpoint_payload: object) -> dict[str, Any]:
    """从 checkpoint 载荷中提取 PyTorch state_dict。"""

    if _looks_like_state_dict(checkpoint_payload):
        return dict(checkpoint_payload)

    if isinstance(checkpoint_payload, dict):
        for key in ("model_state_dict", "state_dict", "ema_state_dict"):
            candidate = checkpoint_payload.get(key)
            if _looks_like_state_dict(candidate):
                return dict(candidate)

        for key in ("ema", "model"):
            candidate = checkpoint_payload.get(key)
            if hasattr(candidate, "state_dict"):
                state_dict = candidate.state_dict()
                if _looks_like_state_dict(state_dict):
                    return dict(state_dict)

    if hasattr(checkpoint_payload, "state_dict"):
        state_dict = checkpoint_payload.state_dict()
        if _looks_like_state_dict(state_dict):
            return dict(state_dict)

    raise ServiceConfigurationError("当前 YOLO checkpoint 不包含可用的状态字典")


def _load_pickle_checkpoint_payload(
    *,
    torch_module: Any,
    checkpoint_path: Path,
    pickle_class_binders: tuple[Callable[..., None], ...],
) -> object:
    """读取需要旧模块路径映射的完整模型 pickle checkpoint。"""

    with _temporary_pickle_checkpoint_modules(
        pickle_class_binders=pickle_class_binders,
    ):
        return torch_module.load(
            str(checkpoint_path),
            map_location="cpu",
            weights_only=False,
        )


@contextmanager
def _temporary_pickle_checkpoint_modules(
    *,
    pickle_class_binders: tuple[Callable[..., None], ...],
):
    """临时注册完整模型 pickle 反序列化需要的旧模块路径。"""

    previous_modules = {
        module_name: sys.modules.get(module_name, _MISSING_MODULE)
        for module_name in _PICKLE_CHECKPOINT_MODULE_NAMES
    }

    root_module = types.ModuleType("ultralytics")
    nn_module = types.ModuleType("ultralytics.nn")
    modules_module = types.ModuleType("ultralytics.nn.modules")
    block_module = types.ModuleType("ultralytics.nn.modules.block")
    conv_module = types.ModuleType("ultralytics.nn.modules.conv")
    head_module = types.ModuleType("ultralytics.nn.modules.head")
    tasks_module = types.ModuleType("ultralytics.nn.tasks")

    root_module.nn = nn_module
    nn_module.modules = modules_module
    nn_module.tasks = tasks_module
    modules_module.block = block_module
    modules_module.conv = conv_module
    modules_module.head = head_module

    _bind_pickle_checkpoint_classes(
        block_module=block_module,
        conv_module=conv_module,
        head_module=head_module,
        tasks_module=tasks_module,
        pickle_class_binders=pickle_class_binders,
    )

    try:
        sys.modules["ultralytics"] = root_module
        sys.modules["ultralytics.nn"] = nn_module
        sys.modules["ultralytics.nn.modules"] = modules_module
        sys.modules["ultralytics.nn.modules.block"] = block_module
        sys.modules["ultralytics.nn.modules.conv"] = conv_module
        sys.modules["ultralytics.nn.modules.head"] = head_module
        sys.modules["ultralytics.nn.tasks"] = tasks_module
        yield
    finally:
        for module_name, previous_module in previous_modules.items():
            if previous_module is _MISSING_MODULE:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module


def _bind_pickle_checkpoint_classes(
    *,
    block_module: types.ModuleType,
    conv_module: types.ModuleType,
    head_module: types.ModuleType,
    tasks_module: types.ModuleType,
    pickle_class_binders: tuple[Callable[..., None], ...],
) -> None:
    """把旧 checkpoint 中的类名映射到项目内 YOLO core 实现。"""

    from backend.service.application.models.yolo_core_common import (
        Classify,
        Conv,
        Detect,
        DistributionFocalLossDecoder,
        DWConv,
        OBB,
        Pose,
        Proto,
        Segment,
    )
    from backend.service.application.models.yolo_core_common.primary.yolo_detection_model import (
        Attention,
        Bottleneck,
        C2PSA,
        C2f,
        C3,
        C3k,
        C3k2,
        Concat,
        PSABlock,
        SPPF,
        YoloDetectionModel,
    )

    block_module.Attention = Attention
    block_module.Bottleneck = Bottleneck
    block_module.C2PSA = C2PSA
    block_module.C2f = C2f
    block_module.C3 = C3
    block_module.C3k = C3k
    block_module.C3k2 = C3k2
    block_module.DFL = DistributionFocalLossDecoder
    block_module.PSABlock = PSABlock
    block_module.Proto = Proto
    block_module.SPPF = SPPF
    conv_module.Concat = Concat
    conv_module.Conv = Conv
    conv_module.DWConv = DWConv
    head_module.Classify = Classify
    head_module.Detect = Detect
    head_module.OBB = OBB
    head_module.Pose = Pose
    head_module.Segment = Segment
    tasks_module.ClassificationModel = YoloDetectionModel
    tasks_module.DetectionModel = YoloDetectionModel
    tasks_module.OBBModel = YoloDetectionModel
    tasks_module.PoseModel = YoloDetectionModel
    tasks_module.SegmentationModel = YoloDetectionModel
    for binder in pickle_class_binders:
        binder(
            block_module=block_module,
            conv_module=conv_module,
            head_module=head_module,
            tasks_module=tasks_module,
        )


def _build_loadable_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> OrderedDict[str, Any]:
    """按目标模型 key 和 shape 筛出可加载权重。"""

    model_state_dict = model.state_dict()
    model_keys = set(model_state_dict)
    loadable_state_dict: OrderedDict[str, Any] = OrderedDict()
    for source_key, source_value in source_state_dict.items():
        normalized_key = _resolve_yolo_source_key(
            key=str(source_key),
            model_keys=model_keys,
        )
        if normalized_key.endswith(YOLO_IGNORED_SOURCE_KEY_SUFFIXES):
            continue
        model_value = model_state_dict.get(normalized_key)
        if model_value is None:
            continue
        if tuple(model_value.shape) != tuple(source_value.shape):
            continue
        loadable_state_dict[normalized_key] = source_value
    return loadable_state_dict


def _looks_like_state_dict(value: object) -> bool:
    """判断对象是否符合 PyTorch state_dict 的基本形态。"""

    if not isinstance(value, dict) or not value:
        return False
    for key, item in value.items():
        if not isinstance(key, str):
            return False
        if not hasattr(item, "shape") and not hasattr(item, "dtype"):
            return False
    return True


def _resolve_yolo_source_key(
    *,
    key: str,
    model_keys: set[str],
) -> str:
    """按 YOLO 常见 checkpoint 前缀把来源 key 归一到项目内 key。"""

    if key in model_keys:
        return key
    normalized_key = key
    prefix_removed = True
    while prefix_removed:
        prefix_removed = False
        for prefix in ("model.", "module."):
            if normalized_key.startswith(prefix):
                normalized_key = normalized_key[len(prefix) :]
                if normalized_key in model_keys:
                    return normalized_key
                prefix_removed = True
    return normalized_key
