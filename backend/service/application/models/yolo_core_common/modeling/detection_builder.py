"""YOLO 主线 detection 模型的共享结构与权重加载实现。"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
import sys
import types
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
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
from backend.service.application.models.yolo_core_common.modeling.detection_model import (
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
    build_yolo_detection_model,
)


YOLOV8_DETECTION_MODEL_CONFIG: dict[str, object] = {
    "reg_max": 16,
    "strides": (8, 16, 32),
    "legacy_class_head": True,
    "scales": {
        "nano": (0.33, 0.25, 1024),
        "s": (0.33, 0.50, 1024),
        "m": (0.67, 0.75, 768),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.25, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 3, "C2f", (128, True)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 6, "C2f", (256, True)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 6, "C2f", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 3, "C2f", (1024, True)),
        (-1, 1, "SPPF", (1024, 5)),
    ],
    "head": [
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 6), 1, "Concat", (1,)),
        (-1, 3, "C2f", (512,)),
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 4), 1, "Concat", (1,)),
        (-1, 3, "C2f", (256,)),
        (-1, 1, "Conv", (256, 3, 2)),
        ((-1, 12), 1, "Concat", (1,)),
        (-1, 3, "C2f", (512,)),
        (-1, 1, "Conv", (512, 3, 2)),
        ((-1, 9), 1, "Concat", (1,)),
        (-1, 3, "C2f", (1024,)),
        ((15, 18, 21), 1, "Detect", ("nc",)),
    ],
}

YOLO11_DETECTION_MODEL_CONFIG: dict[str, object] = {
    "reg_max": 16,
    "strides": (8, 16, 32),
    "scales": {
        "nano": (0.50, 0.25, 1024),
        "s": (0.50, 0.50, 1024),
        "m": (0.50, 1.00, 512),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.50, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 2, "C3k2", (256, False, 0.25)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 2, "C3k2", (512, False, 0.25)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 2, "C3k2", (1024, True)),
        (-1, 1, "SPPF", (1024, 5)),
        (-1, 2, "C2PSA", (1024,)),
    ],
    "head": [
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 6), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (512, False)),
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 4), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (256, False)),
        (-1, 1, "Conv", (256, 3, 2)),
        ((-1, 13), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (512, False)),
        (-1, 1, "Conv", (512, 3, 2)),
        ((-1, 10), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (1024, True)),
        ((16, 19, 22), 1, "Detect", ("nc",)),
    ],
}

YOLO26_DETECTION_MODEL_CONFIG: dict[str, object] = {
    "reg_max": 1,
    "end2end": True,
    "strides": (8, 16, 32),
    "scales": {
        "nano": (0.50, 0.25, 1024),
        "s": (0.50, 0.50, 1024),
        "m": (0.50, 1.00, 512),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.50, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 2, "C3k2", (256, False, 0.25)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 2, "C3k2", (512, False, 0.25)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 2, "C3k2", (1024, True)),
        (-1, 1, "SPPF", (1024, 5, 3, True)),
        (-1, 2, "C2PSA", (1024,)),
    ],
    "head": [
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 6), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "nn.Upsample", (None, 2, "nearest")),
        ((-1, 4), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (256, True)),
        (-1, 1, "Conv", (256, 3, 2)),
        ((-1, 13), 1, "Concat", (1,)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (512, 3, 2)),
        ((-1, 10), 1, "Concat", (1,)),
        (-1, 1, "C3k2", (1024, True, 0.5, True)),
        ((16, 19, 22), 1, "Detect", ("nc",)),
    ],
}

YOLO_TASK_DETECTION_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    "yolov8": YOLOV8_DETECTION_MODEL_CONFIG,
    "yolo11": YOLO11_DETECTION_MODEL_CONFIG,
    "yolo26": YOLO26_DETECTION_MODEL_CONFIG,
}

_IGNORED_SOURCE_ONLY_SUFFIXES = ("dfl.conv.weight",)
_MISSING_MODULE = object()

_ULTRALYTICS_CHECKPOINT_MODULE_NAMES = (
    "ultralytics",
    "ultralytics.nn",
    "ultralytics.nn.modules",
    "ultralytics.nn.modules.block",
    "ultralytics.nn.modules.conv",
    "ultralytics.nn.modules.head",
    "ultralytics.nn.tasks",
)


def build_yolo_task_detection_model(
    *,
    model_type: str,
    model_scale: str,
    num_classes: int,
) -> Any:
    """按模型分类构建一套 YOLO 主线 detection 模型。"""

    model_config = YOLO_TASK_DETECTION_MODEL_CONFIGS.get(model_type)
    if model_config is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLO 主线 detection 模型分类",
            details={"model_type": model_type},
        )
    return build_yolo_detection_model(
        model_name=model_type,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
    )


def load_yolo_task_checkpoint(
    *,
    imports: Any,
    model: Any,
    checkpoint_path: Path,
) -> dict[str, object]:
    """把外部或项目内 checkpoint 归一后加载到当前模型结构。"""

    checkpoint_payload = _load_checkpoint_payload(imports=imports, checkpoint_path=checkpoint_path)
    checkpoint_state_dict = _extract_checkpoint_state_dict(checkpoint_payload)
    normalized_state_dict = _normalize_checkpoint_state_dict(
        state_dict=checkpoint_state_dict,
        model_state_dict=model.state_dict(),
    )
    model_state_dict = model.state_dict()
    filtered_state_dict, shape_mismatch_keys, ignored_source_keys, unexpected_keys = (
        _filter_compatible_checkpoint_state_dict(
            normalized_state_dict=normalized_state_dict,
            model_state_dict=model_state_dict,
        )
    )
    load_result = model.load_state_dict(filtered_state_dict, strict=False)

    remaining_missing_keys = [
        key
        for key in load_result.missing_keys
        if key not in shape_mismatch_keys and key not in _derive_ignored_missing_keys(ignored_source_keys)
    ]
    if remaining_missing_keys or unexpected_keys:
        raise ServiceConfigurationError(
            "当前 YOLO checkpoint 与项目内模型结构不兼容",
            details={
                "checkpoint_path": str(checkpoint_path),
                "missing_keys": remaining_missing_keys,
                "shape_mismatch_keys": shape_mismatch_keys,
                "unexpected_keys": unexpected_keys,
                "ignored_source_keys": ignored_source_keys,
            },
        )
    return {
        "checkpoint_path": str(checkpoint_path),
        "loaded_key_count": len(filtered_state_dict),
        "shape_mismatch_keys": shape_mismatch_keys,
        "unexpected_keys": unexpected_keys,
        "ignored_source_keys": ignored_source_keys,
    }


def _load_checkpoint_payload(*, imports: Any, checkpoint_path: Path) -> object:
    """读取 checkpoint 文件内容。"""

    load_errors: list[str] = []
    for weights_only in (True, False):
        try:
            return imports.torch.load(
                str(checkpoint_path),
                map_location="cpu",
                weights_only=weights_only,
            )
        except TypeError:
            try:
                return imports.torch.load(str(checkpoint_path), map_location="cpu")
            except Exception as error:  # pragma: no cover - 仅在 checkpoint 不合法时进入
                load_errors.append(str(error))
        except Exception as error:
            load_errors.append(str(error))
    try:
        return _load_ultralytics_style_checkpoint_payload(
            imports=imports,
            checkpoint_path=checkpoint_path,
        )
    except Exception as error:
        load_errors.append(str(error))
    raise ServiceConfigurationError(
        "当前 YOLO checkpoint 无法加载为项目内模型权重",
        details={"checkpoint_path": str(checkpoint_path), "errors": load_errors},
    )


def _load_ultralytics_style_checkpoint_payload(*, imports: Any, checkpoint_path: Path) -> object:
    """读取 Ultralytics 风格的完整模型 checkpoint。

    本项目不把 ultralytics Python 包作为运行时依赖。部分本地预训练 .pt
    文件是完整 pickle checkpoint，反序列化时会按旧模块路径查找
    ultralytics.nn.* 类。这里仅在普通 torch.load 已失败后，临时把这些
    类名映射到项目内等价实现，用于提取 state_dict。
    """

    with _temporary_ultralytics_checkpoint_modules():
        return imports.torch.load(
            str(checkpoint_path),
            map_location="cpu",
            weights_only=False,
        )


@contextmanager
def _temporary_ultralytics_checkpoint_modules():
    """临时注册 checkpoint 反序列化需要的 ultralytics 模块路径。"""

    previous_modules = {
        module_name: sys.modules.get(module_name, _MISSING_MODULE)
        for module_name in _ULTRALYTICS_CHECKPOINT_MODULE_NAMES
    }

    ultralytics_module = types.ModuleType("ultralytics")
    nn_module = types.ModuleType("ultralytics.nn")
    modules_module = types.ModuleType("ultralytics.nn.modules")
    block_module = types.ModuleType("ultralytics.nn.modules.block")
    conv_module = types.ModuleType("ultralytics.nn.modules.conv")
    head_module = types.ModuleType("ultralytics.nn.modules.head")
    tasks_module = types.ModuleType("ultralytics.nn.tasks")

    ultralytics_module.nn = nn_module
    nn_module.modules = modules_module
    nn_module.tasks = tasks_module
    modules_module.block = block_module
    modules_module.conv = conv_module
    modules_module.head = head_module

    from backend.service.application.models.yolo26_core.tasks import (
        OBB26,
        Pose26,
        Proto26,
        RealNVP,
        Segment26,
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
    block_module.Proto26 = Proto26
    block_module.SPPF = SPPF
    conv_module.Concat = Concat
    conv_module.Conv = Conv
    conv_module.DWConv = DWConv
    head_module.Classify = Classify
    head_module.Detect = Detect
    head_module.OBB = OBB
    head_module.OBB26 = OBB26
    head_module.Pose = Pose
    head_module.Pose26 = Pose26
    head_module.RealNVP = RealNVP
    head_module.Segment = Segment
    head_module.Segment26 = Segment26
    tasks_module.ClassificationModel = YoloDetectionModel
    tasks_module.DetectionModel = YoloDetectionModel
    tasks_module.OBBModel = YoloDetectionModel
    tasks_module.PoseModel = YoloDetectionModel
    tasks_module.SegmentationModel = YoloDetectionModel

    try:
        sys.modules["ultralytics"] = ultralytics_module
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


def _extract_checkpoint_state_dict(checkpoint_payload: object) -> dict[str, object]:
    """从 checkpoint 载荷中提取状态字典。"""

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


def _looks_like_state_dict(value: object) -> bool:
    """判断一个对象是否像 PyTorch 状态字典。"""

    if not isinstance(value, dict) or not value:
        return False
    for key, item in value.items():
        if not isinstance(key, str):
            return False
        if not hasattr(item, "shape") and not hasattr(item, "dtype"):
            return False
    return True


def _normalize_checkpoint_state_dict(
    *,
    state_dict: dict[str, object],
    model_state_dict: dict[str, object],
) -> OrderedDict[str, object]:
    """规范化外部 checkpoint 的 key 形式。"""

    normalized_state_dict: OrderedDict[str, object] = OrderedDict()
    for key, value in state_dict.items():
        normalized_key = _normalize_checkpoint_key(str(key))
        if normalized_key not in model_state_dict and f"model.{normalized_key}" in model_state_dict:
            normalized_key = f"model.{normalized_key}"
        normalized_state_dict[normalized_key] = value
    return normalized_state_dict


def _normalize_checkpoint_key(key: str) -> str:
    """把 checkpoint 的单个参数名规整成项目内风格。"""

    normalized_key = key
    for prefix in ("module.",):
        if normalized_key.startswith(prefix):
            normalized_key = normalized_key[len(prefix) :]
    if normalized_key.startswith("model.model."):
        normalized_key = normalized_key[len("model.") :]
    return normalized_key


def _filter_compatible_checkpoint_state_dict(
    *,
    normalized_state_dict: OrderedDict[str, object],
    model_state_dict: dict[str, object],
) -> tuple[OrderedDict[str, object], list[str], list[str], list[str]]:
    """筛出当前模型可以安全加载的 checkpoint 参数。"""

    filtered_state_dict: OrderedDict[str, object] = OrderedDict()
    shape_mismatch_keys: list[str] = []
    ignored_source_keys: list[str] = []
    unexpected_keys: list[str] = []

    for key, value in normalized_state_dict.items():
        if _is_ignored_source_only_key(key):
            ignored_source_keys.append(key)
            continue
        expected_value = model_state_dict.get(key)
        if expected_value is None:
            unexpected_keys.append(key)
            continue
        expected_shape = tuple(int(item) for item in expected_value.shape)
        actual_shape = tuple(int(item) for item in value.shape)
        if expected_shape != actual_shape:
            shape_mismatch_keys.append(key)
            continue
        filtered_state_dict[key] = value

    return (
        filtered_state_dict,
        shape_mismatch_keys,
        ignored_source_keys,
        unexpected_keys,
    )


def _is_ignored_source_only_key(key: str) -> bool:
    """判断某个来源 key 是否属于可忽略的只读辅助参数。"""

    return key.endswith(_IGNORED_SOURCE_ONLY_SUFFIXES)


def _derive_ignored_missing_keys(ignored_source_keys: list[str]) -> set[str]:
    """根据来源忽略 key 推导项目内允许缺失的参数。"""

    ignored_missing_keys: set[str] = set()
    for key in ignored_source_keys:
        if key.endswith("dfl.conv.weight"):
            ignored_missing_keys.add(key.removesuffix("dfl.conv.weight") + "dfl.projection")
    return ignored_missing_keys
