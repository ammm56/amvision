"""YOLOv8 detection 的项目内结构实现与 checkpoint 加载。"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo_detection_model import build_yolo_detection_model


YOLOV8_DETECTION_MODEL_CONFIG: dict[str, object] = {
    "reg_max": 16,
    "strides": (8, 16, 32),
    "scales": {
        "n": (0.33, 0.25, 1024),
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


def build_yolov8_detection_model(*, model_scale: str, num_classes: int) -> Any:
    """构建一套 YOLOv8 detection 模型。"""

    return build_yolo_detection_model(
        model_name="yolov8",
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=YOLOV8_DETECTION_MODEL_CONFIG,
    )


def load_yolov8_checkpoint(
    *,
    imports: Any,
    model: Any,
    checkpoint_path: Path,
) -> dict[str, object]:
    """把 checkpoint 权重加载到项目内 YOLOv8 模型结构。"""

    checkpoint_payload = _load_checkpoint_payload(imports=imports, checkpoint_path=checkpoint_path)
    checkpoint_state_dict = _extract_checkpoint_state_dict(checkpoint_payload)
    normalized_state_dict = _normalize_checkpoint_state_dict(checkpoint_state_dict)
    load_result = model.load_state_dict(normalized_state_dict, strict=False)

    ignored_missing_keys = {
        "model.22.dfl.projection",
    }
    missing_keys = [key for key in load_result.missing_keys if key not in ignored_missing_keys]
    if missing_keys:
        raise ServiceConfigurationError(
            "YOLOv8 checkpoint 与当前项目内模型结构不兼容",
            details={
                "checkpoint_path": str(checkpoint_path),
                "missing_keys": missing_keys,
                "unexpected_keys": list(load_result.unexpected_keys),
            },
        )
    return {
        "checkpoint_path": str(checkpoint_path),
        "unexpected_keys": list(load_result.unexpected_keys),
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
    raise ServiceConfigurationError(
        "当前 YOLOv8 checkpoint 无法加载为项目内模型权重",
        details={"checkpoint_path": str(checkpoint_path), "errors": load_errors},
    )


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

    raise ServiceConfigurationError("当前 YOLOv8 checkpoint 不包含可用的状态字典")


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


def _normalize_checkpoint_state_dict(state_dict: dict[str, object]) -> OrderedDict[str, object]:
    """规范化外部 checkpoint 的 key 形式。"""

    normalized_state_dict: OrderedDict[str, object] = OrderedDict()
    known_prefixes = ("module.",)
    for key, value in state_dict.items():
        normalized_key = str(key)
        for prefix in known_prefixes:
            if normalized_key.startswith(prefix):
                normalized_key = normalized_key[len(prefix) :]
        if normalized_key.startswith("model.model."):
            normalized_key = normalized_key[len("model.") :]
        normalized_state_dict[normalized_key] = value
    return normalized_state_dict
