"""RF-DETR core 模型结构模块：`models.weights`。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, List

import torch
import torch.nn.functional as F  # noqa: N812

from backend.service.application.models.validation.model_core_validation import (
    StateDictCoverageSummary,
    analyze_state_dict_coverage,
)
from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.utilities.decorators import deprecated
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger
from backend.service.application.models.rfdetr_core.utilities.state_dict import _ckpt_args_get, validate_checkpoint_compatibility

logger = get_logger()

__all__ = [
    "analyze_rfdetr_checkpoint_coverage",
    "analyze_rfdetr_checkpoint_load_coverage",
    "apply_lora",
    "interpolate_position_embeddings",
    "load_pretrain_weights",
    "load_rfdetr_checkpoint_state_dict",
]

_PE_KEY_SUFFIX = "embeddings.position_embeddings"

_QUERY_PARAM_SUFFIXES: tuple[str, ...] = ("refpoint_embed.weight", "query_feat.weight")


def _require_local_checkpoint(path: str) -> Path:
    """执行 `_require_local_checkpoint`。
    
    参数：
    - `path`：传入的 `path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    checkpoint_path = Path(path).expanduser().resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(
            "RF-DETR 预训练 checkpoint 不存在。"
            f"请先把文件放到本地模型目录，或显式传入有效路径：{checkpoint_path}"
        )
    if checkpoint_path.stat().st_size <= 0:
        raise ValueError(f"RF-DETR 预训练 checkpoint 是空文件：{checkpoint_path}")
    return checkpoint_path


def load_rfdetr_checkpoint_state_dict(path: str | Path) -> dict[str, torch.Tensor]:
    """执行 `load_rfdetr_checkpoint_state_dict`。
    
    参数：
    - `path`：传入的 `path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checkpoint_path = _require_local_checkpoint(str(path))
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    normalized = _normalize_checkpoint_payload(checkpoint, checkpoint_path)
    return dict(normalized["model"])


def analyze_rfdetr_checkpoint_coverage(
    *,
    model: torch.nn.Module,
    checkpoint_path: str | Path,
    ignored_model_key_suffixes: tuple[str, ...] = (),
    ignored_source_key_suffixes: tuple[str, ...] = (),
) -> StateDictCoverageSummary:
    """执行 `analyze_rfdetr_checkpoint_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `ignored_model_key_suffixes`：传入的 `ignored_model_key_suffixes` 参数。
    - `ignored_source_key_suffixes`：传入的 `ignored_source_key_suffixes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    source_state_dict = load_rfdetr_checkpoint_state_dict(checkpoint_path)
    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        ignored_model_key_suffixes=ignored_model_key_suffixes,
        ignored_source_key_suffixes=ignored_source_key_suffixes,
    )


def analyze_rfdetr_checkpoint_load_coverage(
    *,
    model: torch.nn.Module,
    checkpoint_path: str | Path,
    ignored_model_key_suffixes: tuple[str, ...] = (),
    ignored_source_key_suffixes: tuple[str, ...] = (),
) -> StateDictCoverageSummary:
    """执行 `analyze_rfdetr_checkpoint_load_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `ignored_model_key_suffixes`：传入的 `ignored_model_key_suffixes` 参数。
    - `ignored_source_key_suffixes`：传入的 `ignored_source_key_suffixes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checkpoint_path_obj = _require_local_checkpoint(str(checkpoint_path))
    checkpoint = torch.load(checkpoint_path_obj, map_location="cpu", weights_only=False)
    normalized = _normalize_checkpoint_payload(checkpoint, checkpoint_path_obj)
    source_state_dict = _build_load_path_coverage_state_dict(
        model=model,
        checkpoint=normalized,
    )
    return analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
        ignored_model_key_suffixes=ignored_model_key_suffixes,
        ignored_source_key_suffixes=ignored_source_key_suffixes,
    )


def _build_load_path_coverage_state_dict(
    *,
    model: torch.nn.Module,
    checkpoint: dict[str, Any],
) -> dict[str, torch.Tensor]:
    """执行 `_build_load_path_coverage_state_dict`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `checkpoint`：传入的 `checkpoint` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    source_state_dict = dict(checkpoint["model"])
    _adapt_query_params_for_load_coverage(
        model=model,
        source_state_dict=source_state_dict,
        checkpoint_args=checkpoint.get("args"),
    )
    return source_state_dict


def _adapt_query_params_for_load_coverage(
    *,
    model: torch.nn.Module,
    source_state_dict: dict[str, torch.Tensor],
    checkpoint_args: Any,
) -> None:
    """执行 `_adapt_query_params_for_load_coverage`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `source_state_dict`：传入的 `source_state_dict` 参数。
    - `checkpoint_args`：传入的 `checkpoint_args` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    model_state_dict = model.state_dict()
    target_num_queries = _coerce_positive_int(getattr(model, "num_queries", None))
    target_group_detr = _coerce_positive_int(getattr(model, "group_detr", None))
    ckpt_num_queries = _coerce_positive_int(_ckpt_args_get(checkpoint_args, "num_queries"))
    ckpt_group_detr = _coerce_positive_int(_ckpt_args_get(checkpoint_args, "group_detr"))

    for name, tensor in list(source_state_dict.items()):
        if not any(name.endswith(suffix) for suffix in _QUERY_PARAM_SUFFIXES):
            continue
        target_tensor = model_state_dict.get(name)
        if target_tensor is None or tuple(tensor.shape) == tuple(target_tensor.shape):
            continue
        if len(tensor.shape) != len(target_tensor.shape) or tuple(tensor.shape[1:]) != tuple(target_tensor.shape[1:]):
            continue
        if tensor.shape[0] < target_tensor.shape[0]:
            continue
        if ckpt_num_queries is not None and ckpt_group_detr is not None and target_num_queries is not None and target_group_detr is not None:
            source_state_dict[name] = _slice_query_param_per_group(
                tensor,
                ckpt_num_queries=ckpt_num_queries,
                ckpt_group_detr=ckpt_group_detr,
                target_num_queries=target_num_queries,
                target_group_detr=target_group_detr,
            )
        else:
            source_state_dict[name] = tensor[: target_tensor.shape[0]]


def _coerce_positive_int(value: Any) -> int | None:
    """执行 `_coerce_positive_int`。
    
    参数：
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    if integer <= 0:
        return None
    return integer


def _normalize_checkpoint_payload(
    checkpoint: Any,
    checkpoint_path: Path,
) -> dict[str, Any]:
    """执行 `_normalize_checkpoint_payload`。
    
    参数：
    - `checkpoint`：传入的 `checkpoint` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if not isinstance(checkpoint, Mapping):
        raise ValueError(f"RF-DETR checkpoint 不是有效字典：{checkpoint_path}")

    if "model" in checkpoint:
        model_state = _coerce_tensor_state_dict(
            checkpoint["model"],
            checkpoint_path=checkpoint_path,
            source_name="model",
        )
        normalized = dict(checkpoint)
        normalized["model"] = model_state
        return normalized

    if "state_dict" in checkpoint:
        model_state = _normalize_lightning_state_dict(
            checkpoint["state_dict"],
            checkpoint_path=checkpoint_path,
        )
        normalized = dict(checkpoint)
        normalized["model"] = model_state
        if "args" not in normalized and "hyper_parameters" in normalized:
            normalized["args"] = normalized["hyper_parameters"]
        return normalized

    if _looks_like_tensor_state_dict(checkpoint):
        return {"model": _coerce_tensor_state_dict(checkpoint, checkpoint_path=checkpoint_path, source_name="raw")}

    raise ValueError(
        "RF-DETR checkpoint 缺少可识别的权重字段。"
        f"需要顶层包含 model、state_dict，或文件本身是裸 state_dict：{checkpoint_path}"
    )


def _normalize_lightning_state_dict(
    state_dict: Any,
    *,
    checkpoint_path: Path,
) -> dict[str, torch.Tensor]:
    """执行 `_normalize_lightning_state_dict`。
    
    参数：
    - `state_dict`：传入的 `state_dict` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    tensor_state_dict = _coerce_tensor_state_dict(
        state_dict,
        checkpoint_path=checkpoint_path,
        source_name="state_dict",
    )
    prefix = "model."
    compile_prefix = "_orig_mod."
    model_state: dict[str, torch.Tensor] = {}
    for key, tensor in tensor_state_dict.items():
        if not key.startswith(prefix):
            continue
        stripped = key[len(prefix) :]
        if stripped.startswith(compile_prefix):
            stripped = stripped[len(compile_prefix) :]
        model_state[stripped] = tensor
    if not model_state:
        raise ValueError(
            f"RF-DETR Lightning checkpoint 的 state_dict 中没有 model. 前缀参数：{checkpoint_path}"
        )
    return model_state


def _coerce_tensor_state_dict(
    value: Any,
    *,
    checkpoint_path: Path,
    source_name: str,
) -> dict[str, torch.Tensor]:
    """执行 `_coerce_tensor_state_dict`。
    
    参数：
    - `value`：传入的 `value` 参数。
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `source_name`：传入的 `source_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if not isinstance(value, Mapping):
        raise ValueError(f"RF-DETR checkpoint 的 {source_name} 不是字典：{checkpoint_path}")
    tensor_state_dict = {
        str(key): tensor for key, tensor in value.items() if torch.is_tensor(tensor)
    }
    if not tensor_state_dict:
        raise ValueError(f"RF-DETR checkpoint 的 {source_name} 中没有 Tensor 权重：{checkpoint_path}")
    return tensor_state_dict


def _looks_like_tensor_state_dict(value: Mapping[Any, Any]) -> bool:
    """执行 `_looks_like_tensor_state_dict`。
    
    参数：
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return bool(value) and all(isinstance(key, str) and torch.is_tensor(tensor) for key, tensor in value.items())


def _slice_query_param_per_group(
    tensor: torch.Tensor,
    ckpt_num_queries: int,
    ckpt_group_detr: int,
    target_num_queries: int,
    target_group_detr: int,
) -> torch.Tensor:
    """执行 `_slice_query_param_per_group`。
    
    参数：
    - `tensor`：传入的 `tensor` 参数。
    - `ckpt_num_queries`：传入的 `ckpt_num_queries` 参数。
    - `ckpt_group_detr`：传入的 `ckpt_group_detr` 参数。
    - `target_num_queries`：传入的 `target_num_queries` 参数。
    - `target_group_detr`：传入的 `target_group_detr` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if ckpt_num_queries <= 0 or ckpt_group_detr <= 0 or target_num_queries <= 0 or target_group_detr <= 0:
        raise ValueError(
            f"_slice_query_param_per_group: all dimension args must be positive; "
            f"got ckpt_num_queries={ckpt_num_queries}, ckpt_group_detr={ckpt_group_detr}, "
            f"target_num_queries={target_num_queries}, target_group_detr={target_group_detr}."
        )

    expected_total = ckpt_num_queries * ckpt_group_detr
    if tensor.shape[0] != expected_total:
        logger.warning(
            "_slice_query_param_per_group: checkpoint args claim %d × %d = %d rows "
            "but tensor has %d rows; falling back to flat slice. Per-group structure "
            "may be scrambled if group_detr > 1.",
            ckpt_num_queries,
            ckpt_group_detr,
            expected_total,
            tensor.shape[0],
        )
        return tensor[: target_num_queries * target_group_detr]

    if target_num_queries == ckpt_num_queries and target_group_detr == ckpt_group_detr:
        return tensor

    keep_groups = min(target_group_detr, ckpt_group_detr)
    keep_per_group = min(target_num_queries, ckpt_num_queries)
    pieces = [tensor[g * ckpt_num_queries : g * ckpt_num_queries + keep_per_group] for g in range(keep_groups)]
    return torch.cat(pieces, dim=0)


def _filter_intentional_keys(keys: list[str]) -> list[str]:
    """执行 `_filter_intentional_keys`。
    
    参数：
    - `keys`：传入的 `keys` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    intentional_patterns: tuple[str, ...] = (
        "class_embed.",
        "bbox_embed.",
        *_QUERY_PARAM_SUFFIXES,
        "enc_out_class_embed.",
        "enc_out_bbox_embed.",
    )

    def _is_intentional(key: str) -> bool:
        return any(key.startswith(pat) or f".{pat}" in key for pat in intentional_patterns)

    return [k for k in keys if not _is_intentional(k)]


def _warn_on_partial_load(incompatible: Any, pretrain_weights_path: str) -> None:
    """执行 `_warn_on_partial_load`。
    
    参数：
    - `incompatible`：传入的 `incompatible` 参数。
    - `pretrain_weights_path`：传入的 `pretrain_weights_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    missing_keys_raw = getattr(incompatible, "missing_keys", None)
    unexpected_keys_raw = getattr(incompatible, "unexpected_keys", None)
    try:
        missing_keys = [str(k) for k in missing_keys_raw] if missing_keys_raw else []
        unexpected_keys = [str(k) for k in unexpected_keys_raw] if unexpected_keys_raw else []
    except TypeError:
        return
    missing = _filter_intentional_keys(missing_keys)
    unexpected = _filter_intentional_keys(unexpected_keys)
    if not missing and not unexpected:
        return

    parts: list[str] = []
    if missing:
        sample = ", ".join(missing[:5])
        if len(missing) > 5:
            sample += ", ..."
        parts.append(f"{len(missing)} model parameter(s) not in checkpoint (left at random init): [{sample}]")
    if unexpected:
        sample = ", ".join(unexpected[:5])
        if len(unexpected) > 5:
            sample += ", ..."
        parts.append(f"{len(unexpected)} checkpoint key(s) not consumed by model: [{sample}]")

    logger.warning(
        "Pretrained weights at %r loaded only partially — this typically produces "
        "lower accuracy. %s. Check that the model configuration (encoder, hidden_dim, "
        "out_feature_indexes, projector_scale, ...) matches the architecture the "
        "checkpoint was trained with.",
        pretrain_weights_path,
        " ".join(parts),
    )


def interpolate_position_embeddings(
    checkpoint_state: dict,
    pe_size: int,
) -> None:
    """执行 `interpolate_position_embeddings`。
    
    参数：
    - `checkpoint_state`：传入的 `checkpoint_state` 参数。
    - `pe_size`：传入的 `pe_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    n_target = pe_size * pe_size

    pe_keys = [k for k in checkpoint_state if k.endswith(_PE_KEY_SUFFIX)]
    for key in pe_keys:
        ckpt_pe = checkpoint_state[key]
        n_source = ckpt_pe.shape[1] - 1
        if n_source == n_target:
            continue

        h_src = int(math.isqrt(n_source))
        h_tgt = int(math.isqrt(n_target))
        if h_src * h_src != n_source or h_tgt * h_tgt != n_target:
            logger.warning(
                f"Skipping PE interpolation for {key}:"
                f" grid size is not a perfect square (source {n_source}, target {n_target}).",
            )
            continue

        dim = ckpt_pe.shape[-1]
        class_token = ckpt_pe[:, :1]
        patch_pe = ckpt_pe[:, 1:]

        patch_pe = patch_pe.reshape(1, h_src, h_src, dim).permute(0, 3, 1, 2)
        patch_pe = F.interpolate(
            patch_pe.float(),
            size=(h_tgt, h_tgt),
            mode="bicubic",
            align_corners=False,
            antialias=False,
        ).to(ckpt_pe.dtype)
        patch_pe = patch_pe.permute(0, 2, 3, 1).reshape(1, n_target, dim)

        checkpoint_state[key] = torch.cat([class_token, patch_pe], dim=1)
        logger.debug(
            "Interpolated positional embeddings %s: %s → %s.",
            key,
            tuple(ckpt_pe.shape),
            tuple(checkpoint_state[key].shape),
        )


@deprecated(target=True, args_mapping={"train_config": None}, deprecated_in="1.7.0", remove_in="1.9.0", num_warns=-1)
def load_pretrain_weights(
    nn_model: torch.nn.Module,
    model_config: ModelConfig,
    train_config: TrainConfig | None = None,
) -> List[str]:
    """执行 `load_pretrain_weights`。
    
    参数：
    - `nn_model`：传入的 `nn_model` 参数。
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    mc = model_config
    pretrain_weights = mc.pretrain_weights
    if pretrain_weights is None:
        return []
    class_names: List[str] = []
    checkpoint_path = _require_local_checkpoint(pretrain_weights)

    try:
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except Exception:
        logger.info("Failed to load RF-DETR pretrain weights from %s", checkpoint_path)
        raise
    checkpoint = _normalize_checkpoint_payload(checkpoint, checkpoint_path)

    if "args" in checkpoint:
        raw_class_names = _ckpt_args_get(checkpoint["args"], "class_names")
        if raw_class_names:
            if isinstance(raw_class_names, str):
                class_names = [raw_class_names]
            else:
                try:
                    iterator = iter(raw_class_names)
                except TypeError:
                    class_names = []
                else:
                    class_names = [name for name in iterator if isinstance(name, str)]

    validate_checkpoint_compatibility(checkpoint, mc)

    user_set_num_classes = False
    if hasattr(mc, "model_fields_set"):
        user_set_num_classes = "num_classes" in getattr(mc, "model_fields_set", set())
    default_num_classes = type(mc).model_fields["num_classes"].default
    num_classes = mc.num_classes
    user_overrode_default_num_classes = user_set_num_classes and num_classes != default_num_classes

    checkpoint_num_classes = checkpoint["model"]["class_embed.bias"].shape[0]
    configured_num_classes_plus_bg = num_classes + 1
    if checkpoint_num_classes != configured_num_classes_plus_bg:
        if checkpoint_num_classes < configured_num_classes_plus_bg:
            if not user_overrode_default_num_classes:
                num_classes = checkpoint_num_classes - 1
                configured_num_classes_plus_bg = checkpoint_num_classes
                mc.num_classes = num_classes
        nn_model.reinitialize_detection_head(checkpoint_num_classes)

    ckpt_args = checkpoint.get("args")
    ckpt_num_queries_raw = _ckpt_args_get(ckpt_args, "num_queries") if ckpt_args is not None else None
    ckpt_group_detr_raw = _ckpt_args_get(ckpt_args, "group_detr") if ckpt_args is not None else None
    try:
        ckpt_num_queries = int(ckpt_num_queries_raw) if ckpt_num_queries_raw is not None else None
        ckpt_group_detr = int(ckpt_group_detr_raw) if ckpt_group_detr_raw is not None else None
    except (TypeError, ValueError):
        logger.warning(
            "load_pretrain_weights: checkpoint args.num_queries / args.group_detr not coercible "
            "to int; falling back to legacy flat slice."
        )
        ckpt_num_queries = None
        ckpt_group_detr = None
    if (ckpt_num_queries is None) != (ckpt_group_detr is None):
        _first_query_key = next(
            (k for k in checkpoint["model"] if any(k.endswith(s) for s in _QUERY_PARAM_SUFFIXES)),
            None,
        )
        if _first_query_key is not None:
            _n = checkpoint["model"][_first_query_key].shape[0]
            _absent: str | None = None
            if ckpt_num_queries is not None and ckpt_num_queries > 0 and _n % ckpt_num_queries == 0:
                ckpt_group_detr = _n // ckpt_num_queries
                _absent, _inferred, _known, _known_val = "group_detr", ckpt_group_detr, "num_queries", ckpt_num_queries
            elif ckpt_group_detr is not None and ckpt_group_detr > 0 and _n % ckpt_group_detr == 0:
                ckpt_num_queries = _n // ckpt_group_detr
                _absent, _inferred, _known, _known_val = "num_queries", ckpt_num_queries, "group_detr", ckpt_group_detr
            if _absent is not None:
                logger.warning(
                    "load_pretrain_weights: args.%s absent; inferred ckpt_%s=%d from tensor rows %d ÷ ckpt_%s=%d.",
                    _absent,
                    _absent,
                    _inferred,
                    _n,
                    _known,
                    _known_val,
                )
    if mc.group_detr > 1 and (ckpt_num_queries is None or ckpt_group_detr is None):
        logger.warning(
            "load_pretrain_weights: checkpoint lacks args.num_queries / "
            "args.group_detr; falling back to flat slice. With "
            "group_detr=%d this may scramble per-group query structure if "
            "the checkpoint was trained with group_detr > 1.",
            mc.group_detr,
        )
    for name in list(checkpoint["model"].keys()):
        if any(name.endswith(x) for x in _QUERY_PARAM_SUFFIXES):
            tensor = checkpoint["model"][name]
            if ckpt_num_queries is not None and ckpt_group_detr is not None:
                checkpoint["model"][name] = _slice_query_param_per_group(
                    tensor,
                    ckpt_num_queries=ckpt_num_queries,
                    ckpt_group_detr=ckpt_group_detr,
                    target_num_queries=mc.num_queries,
                    target_group_detr=mc.group_detr,
                )
            else:
                checkpoint["model"][name] = tensor[: mc.num_queries * mc.group_detr]

    interpolate_position_embeddings(checkpoint["model"], mc.positional_encoding_size)
    incompatible = nn_model.load_state_dict(checkpoint["model"], strict=False)
    _warn_on_partial_load(incompatible, str(checkpoint_path))

    if checkpoint_num_classes < configured_num_classes_plus_bg and user_overrode_default_num_classes:
        nn_model.reinitialize_detection_head(configured_num_classes_plus_bg)

    if num_classes + 1 < checkpoint_num_classes:
        nn_model.reinitialize_detection_head(num_classes + 1)

    return class_names


def apply_lora(nn_model: torch.nn.Module) -> None:
    """执行 `apply_lora`。
    
    参数：
    - `nn_model`：传入的 `nn_model` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    _ = nn_model
    raise NotImplementedError("当前 RF-DETR core 未启用 LoRA/PEFT 微调；如需该能力，应单独规划并显式引入依赖。")
