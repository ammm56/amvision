"""RF-DETR core 工具函数模块：`utilities.state_dict`。"""

import os
import tempfile
from collections import OrderedDict
from typing import Any

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()

_PTL_COMPAT_KEYS = (
    "state_dict",
    "global_step",
    "pytorch-lightning_version",
    "loops",
    "optimizer_states",
    "lr_schedulers",
)


def _raise_patch_size_mismatch(ckpt_patch_size: int, model_patch_size: int) -> None:
    """执行 `_raise_patch_size_mismatch`。
    
    参数：
    - `ckpt_patch_size`：传入的 `ckpt_patch_size` 参数。
    - `model_patch_size`：传入的 `model_patch_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    raise ValueError(
        f"The checkpoint was trained with patch_size={ckpt_patch_size}, but the current model uses "
        f"patch_size={model_patch_size}. The checkpoint is incompatible with this model architecture. "
        "To resolve this, either instantiate/configure the model with the checkpoint's patch_size or "
        "use a checkpoint that was trained with the same patch_size as the current model."
    )


def _ckpt_args_get(args: Any, field: str, default: Any = None) -> Any:
    """执行 `_ckpt_args_get`。
    
    参数：
    - `args`：传入的 `args` 参数。
    - `field`：传入的 `field` 参数。
    - `default`：传入的 `default` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if isinstance(args, dict):
        return args.get(field, default)
    return getattr(args, field, default)


def _make_fit_loop_state(epoch: int) -> dict:
    """执行 `_make_fit_loop_state`。
    
    参数：
    - `epoch`：传入的 `epoch` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    n = epoch + 1
    zero4 = {"ready": 0, "started": 0, "processed": 0, "completed": 0}
    zero3 = {"ready": 0, "started": 0, "completed": 0}
    zero2 = {"ready": 0, "completed": 0}
    n4 = {"ready": n, "started": n, "processed": n, "completed": n}
    return {
        "state_dict": {},
        "epoch_loop.state_dict": {"_batches_that_stepped": 0},
        "epoch_loop.batch_progress": {
            "total": {**zero4},
            "current": {**zero4},
            "is_last_batch": False,
        },
        "epoch_loop.scheduler_progress": {
            "total": {**zero2},
            "current": {**zero2},
        },
        "epoch_loop.automatic_optimization.state_dict": {},
        "epoch_loop.automatic_optimization.optim_progress": {
            "optimizer": {
                "step": {
                    "total": {**zero2},
                    "current": {**zero2},
                },
                "zero_grad": {
                    "total": {**zero3},
                    "current": {**zero3},
                },
            }
        },
        "epoch_loop.manual_optimization.state_dict": {},
        "epoch_loop.manual_optimization.optim_step_progress": {
            "total": {**zero2},
            "current": {**zero2},
        },
        "epoch_loop.val_loop.state_dict": {},
        "epoch_loop.val_loop.batch_progress": {
            "total": {**zero4},
            "current": {**zero4},
            "is_last_batch": False,
        },
        "epoch_progress": {
            "total": {**n4},
            "current": {**n4},
        },
    }


def strip_checkpoint(checkpoint: str | os.PathLike[str]) -> None:
    """执行 `strip_checkpoint`。
    
    参数：
    - `checkpoint`：传入的 `checkpoint` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    import torch

    state_dict = torch.load(checkpoint, map_location="cpu", weights_only=False)
    new_state_dict = {
        "model": state_dict["model"],
        "args": state_dict["args"],
    }
    if "model_name" in state_dict:
        new_state_dict["model_name"] = state_dict["model_name"]
    if "rfdetr_version" in state_dict:
        new_state_dict["rfdetr_version"] = state_dict["rfdetr_version"]
    for key in _PTL_COMPAT_KEYS:
        if key in state_dict:
            new_state_dict[key] = state_dict[key]
    checkpoint_dir = os.path.dirname(os.path.abspath(os.fspath(checkpoint)))
    with tempfile.NamedTemporaryFile(dir=checkpoint_dir, delete=False) as tmp_file:
        tmp_path = tmp_file.name
    try:
        torch.save(new_state_dict, tmp_path)
        os.replace(tmp_path, checkpoint)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def clean_state_dict(state_dict: dict[str, Any]) -> OrderedDict[str, Any]:
    """执行 `clean_state_dict`。
    
    参数：
    - `state_dict`：传入的 `state_dict` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    new_state_dict = OrderedDict()
    for k, v in state_dict.items():
        if k[:7] == "module.":
            k = k[7:]
        new_state_dict[k] = v
    return new_state_dict


def validate_checkpoint_compatibility(checkpoint: dict[str, Any], model_args: Any) -> None:
    """执行 `validate_checkpoint_compatibility`。
    
    参数：
    - `checkpoint`：传入的 `checkpoint` 参数。
    - `model_args`：传入的 `model_args` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    ckpt_class_bias = checkpoint.get("model", {}).get("class_embed.bias", None)
    if ckpt_class_bias is not None:
        ckpt_num_classes = ckpt_class_bias.shape[0]
        model_num_classes: int | None = getattr(model_args, "num_classes", None)
        if model_num_classes is not None and ckpt_num_classes != model_num_classes + 1:
            if model_num_classes + 1 < ckpt_num_classes:
                logger.warning(
                    "Checkpoint has %d classes but model is configured for %d. "
                    "The detection head will be re-initialized to %d classes.",
                    ckpt_num_classes - 1,
                    model_num_classes,
                    model_num_classes,
                )
            else:
                logger.warning(
                    "Checkpoint has %d classes but model is configured for %d. "
                    "Using checkpoint class count (%d). "
                    "Pass num_classes=%d to suppress this warning.",
                    ckpt_num_classes - 1,
                    model_num_classes,
                    ckpt_num_classes - 1,
                    ckpt_num_classes - 1,
                )

    _ckpt_args = checkpoint.get("args")
    _ckpt_patch_size_from_args: int | None = None
    if _ckpt_args is not None:
        _ckpt_patch_size_from_args = _ckpt_args_get(_ckpt_args, "patch_size")

    if _ckpt_patch_size_from_args is None:
        _patch_proj_key = "backbone.0.encoder.encoder.embeddings.patch_embeddings.projection.weight"
        _ckpt_proj_w = checkpoint.get("model", {}).get(_patch_proj_key)
        _ckpt_proj_shape = getattr(_ckpt_proj_w, "shape", None)
        if _ckpt_proj_shape is not None and len(_ckpt_proj_shape) == 4 and _ckpt_proj_shape[2] == _ckpt_proj_shape[3]:
            _inferred_ps = int(_ckpt_proj_shape[-1])
            _model_ps: int | None = getattr(model_args, "patch_size", None)
            if _model_ps is not None and _inferred_ps != _model_ps:
                _raise_patch_size_mismatch(_inferred_ps, _model_ps)
    if "args" not in checkpoint:
        return

    ckpt_args = checkpoint["args"]
    ckpt_segmentation_head: bool | None = _ckpt_args_get(ckpt_args, "segmentation_head")
    model_segmentation_head: bool | None = getattr(model_args, "segmentation_head", None)

    if (
        ckpt_segmentation_head is not None
        and model_segmentation_head is not None
        and ckpt_segmentation_head != model_segmentation_head
    ):
        if ckpt_segmentation_head:
            raise ValueError(
                "The checkpoint was trained with a segmentation head, but the current model does not have one. "
                "Load the weights into a segmentation model (e.g. RFDETRSegNano) instead of a detection model."
            )
        else:
            raise ValueError(
                "The current model has a segmentation head, but the checkpoint was trained without one. "
                "Load the weights into a detection model (e.g. RFDETRNano) instead of a segmentation model."
            )

    ckpt_patch_size: int | None = _ckpt_args_get(ckpt_args, "patch_size")
    model_patch_size: int | None = getattr(model_args, "patch_size", None)
    if ckpt_patch_size is not None and model_patch_size is not None and ckpt_patch_size != model_patch_size:
        _raise_patch_size_mismatch(ckpt_patch_size, model_patch_size)


