"""YOLOE checkpoint 读取和受控兼容别名。"""

from __future__ import annotations

import contextlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class PromptFreeCheckpointArtifacts:
    """描述 prompt-free checkpoint 解析后的关键信息。"""

    checkpoint_path: Path
    model_name: str
    model_scale: str
    model_config: dict[str, object]
    class_names: dict[int, str]
    input_size: tuple[int, int]
    state_dict: dict[str, torch.Tensor]


class _CheckpointCompatModule(nn.Module):
    """只用于读取 checkpoint 的兼容占位模块。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__()
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> object:
        try:
            return super().__getattr__(name)
        except AttributeError:
            if name.startswith("__"):
                raise
            return lambda *args, **kwargs: None


class _CheckpointCompatConv(_CheckpointCompatModule):
    pass


class _CheckpointCompatDwConv(_CheckpointCompatModule):
    pass


class _CheckpointCompatConcat(_CheckpointCompatModule):
    pass


class _CheckpointCompatC2f(_CheckpointCompatModule):
    pass


class _CheckpointCompatC3(_CheckpointCompatModule):
    pass


class _CheckpointCompatC3k(_CheckpointCompatModule):
    pass


class _CheckpointCompatC3k2(_CheckpointCompatModule):
    pass


class _CheckpointCompatC2PSA(_CheckpointCompatModule):
    pass


class _CheckpointCompatPSABlock(_CheckpointCompatModule):
    pass


class _CheckpointCompatAttention(_CheckpointCompatModule):
    pass


class _CheckpointCompatA2C2f(_CheckpointCompatModule):
    pass


class _CheckpointCompatBottleneck(_CheckpointCompatModule):
    pass


class _CheckpointCompatSPPF(_CheckpointCompatModule):
    pass


class _CheckpointCompatDfl(_CheckpointCompatModule):
    pass


class _CheckpointCompatBatchNormContrastiveHead(_CheckpointCompatModule):
    """兼容 checkpoint 中的 BNContrastiveHead。"""

    @staticmethod
    def forward_fuse(*args: object, **kwargs: object) -> None:
        """兼容 fused head 的反序列化属性访问。"""

        return None


class _CheckpointCompatProto(_CheckpointCompatModule):
    pass


class _CheckpointCompatProto26(_CheckpointCompatModule):
    pass


class _CheckpointCompatResidual(_CheckpointCompatModule):
    pass


class _CheckpointCompatSwiGluFfn(_CheckpointCompatModule):
    pass


class _CheckpointCompatSavpe(_CheckpointCompatModule):
    pass


class _CheckpointCompatLrpcHead(_CheckpointCompatModule):
    pass


class _CheckpointCompatYoloeSegmentHead(_CheckpointCompatModule):
    pass


class _CheckpointCompatYoloeSegment26Head(_CheckpointCompatModule):
    pass


class _CheckpointCompatYoloeSegmentationModel(_CheckpointCompatModule):
    pass


@contextlib.contextmanager
def _temporary_checkpoint_class_aliases():
    """临时注册 Ultralytics YOLOE checkpoint 反序列化所需类名。"""

    alias_modules = {
        "ultralytics": types.ModuleType("ultralytics"),
        "ultralytics.nn": types.ModuleType("ultralytics.nn"),
        "ultralytics.nn.tasks": types.ModuleType("ultralytics.nn.tasks"),
        "ultralytics.nn.modules": types.ModuleType("ultralytics.nn.modules"),
        "ultralytics.nn.modules.conv": types.ModuleType("ultralytics.nn.modules.conv"),
        "ultralytics.nn.modules.block": types.ModuleType("ultralytics.nn.modules.block"),
        "ultralytics.nn.modules.head": types.ModuleType("ultralytics.nn.modules.head"),
    }
    alias_modules["ultralytics.nn.tasks"].YOLOESegModel = _CheckpointCompatYoloeSegmentationModel
    alias_modules["ultralytics.nn.modules.conv"].Conv = _CheckpointCompatConv
    alias_modules["ultralytics.nn.modules.conv"].DWConv = _CheckpointCompatDwConv
    alias_modules["ultralytics.nn.modules.conv"].Concat = _CheckpointCompatConcat
    alias_modules["ultralytics.nn.modules.block"].C2f = _CheckpointCompatC2f
    alias_modules["ultralytics.nn.modules.block"].C3 = _CheckpointCompatC3
    alias_modules["ultralytics.nn.modules.block"].C3k = _CheckpointCompatC3k
    alias_modules["ultralytics.nn.modules.block"].C3k2 = _CheckpointCompatC3k2
    alias_modules["ultralytics.nn.modules.block"].C2PSA = _CheckpointCompatC2PSA
    alias_modules["ultralytics.nn.modules.block"].PSABlock = _CheckpointCompatPSABlock
    alias_modules["ultralytics.nn.modules.block"].Attention = _CheckpointCompatAttention
    alias_modules["ultralytics.nn.modules.block"].A2C2f = _CheckpointCompatA2C2f
    alias_modules["ultralytics.nn.modules.block"].Bottleneck = _CheckpointCompatBottleneck
    alias_modules["ultralytics.nn.modules.block"].SPPF = _CheckpointCompatSPPF
    alias_modules["ultralytics.nn.modules.block"].DFL = _CheckpointCompatDfl
    alias_modules["ultralytics.nn.modules.block"].BNContrastiveHead = _CheckpointCompatBatchNormContrastiveHead
    alias_modules["ultralytics.nn.modules.block"].Proto = _CheckpointCompatProto
    alias_modules["ultralytics.nn.modules.block"].Proto26 = _CheckpointCompatProto26
    alias_modules["ultralytics.nn.modules.block"].SAVPE = _CheckpointCompatSavpe
    alias_modules["ultralytics.nn.modules.block"].Residual = _CheckpointCompatResidual
    alias_modules["ultralytics.nn.modules.block"].SwiGLUFFN = _CheckpointCompatSwiGluFfn
    alias_modules["ultralytics.nn.modules.head"].YOLOESegment = _CheckpointCompatYoloeSegmentHead
    alias_modules["ultralytics.nn.modules.head"].YOLOESegment26 = _CheckpointCompatYoloeSegment26Head
    alias_modules["ultralytics.nn.modules.head"].SAVPE = _CheckpointCompatSavpe
    alias_modules["ultralytics.nn.modules.head"].LRPCHead = _CheckpointCompatLrpcHead
    alias_modules["ultralytics.nn.modules.head"].Residual = _CheckpointCompatResidual
    alias_modules["ultralytics.nn.modules.head"].SwiGLUFFN = _CheckpointCompatSwiGluFfn

    previous_modules = {name: sys.modules.get(name) for name in alias_modules}
    sys.modules.update(alias_modules)
    try:
        yield
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def load_prompt_free_checkpoint_artifacts(*, checkpoint_path: Path) -> PromptFreeCheckpointArtifacts:
    """从 prompt-free checkpoint 提取 project-native 运行时所需数据。"""

    with _temporary_checkpoint_class_aliases():
        checkpoint_payload = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 载入结果不是合法字典",
            details={"checkpoint_path": str(checkpoint_path)},
        )

    checkpoint_model = checkpoint_payload.get("ema") or checkpoint_payload.get("model")
    if not isinstance(checkpoint_model, nn.Module):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少可用模型对象",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    model_config = getattr(checkpoint_model, "yaml", None)
    if not isinstance(model_config, dict):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少模型配置",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    raw_names = getattr(checkpoint_model, "names", None)
    if not isinstance(raw_names, dict) or not raw_names:
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少类别名映射",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    class_names = {int(key): str(value) for key, value in raw_names.items()}
    model_scale = str(model_config.get("scale") or "s").strip().lower()
    train_args = checkpoint_payload.get("train_args")
    if not isinstance(train_args, dict):
        train_args = {}
    input_size = _resolve_checkpoint_input_size(train_args.get("imgsz"))
    return PromptFreeCheckpointArtifacts(
        checkpoint_path=checkpoint_path,
        model_name=str(model_config.get("yaml_file") or checkpoint_path.stem),
        model_scale=model_scale,
        model_config=dict(model_config),
        class_names=class_names,
        input_size=input_size,
        state_dict=dict(checkpoint_model.state_dict()),
    )


def is_ignored_text_prompt_checkpoint_key(key: str) -> bool:
    """判断 text/visual prompt runtime 可忽略的 fused-only checkpoint 分支。"""

    return ".lrpc." in key or ".one2one_" in key


def _resolve_checkpoint_input_size(raw_imgsz: object) -> tuple[int, int]:
    """从 checkpoint train_args 解析输入尺寸。"""

    if isinstance(raw_imgsz, int | float):
        normalized = max(int(raw_imgsz), 32)
        return normalized, normalized
    if isinstance(raw_imgsz, list | tuple) and len(raw_imgsz) >= 2:
        return max(int(raw_imgsz[0]), 32), max(int(raw_imgsz[1]), 32)
    return 640, 640


__all__ = [
    "PromptFreeCheckpointArtifacts",
    "is_ignored_text_prompt_checkpoint_key",
    "load_prompt_free_checkpoint_artifacts",
]
