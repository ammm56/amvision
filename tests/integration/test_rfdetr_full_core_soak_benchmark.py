"""RF-DETR full core 显式短时 smoke / benchmark。

默认不会执行；需要手动设置 `AMVISION_RUN_RFDETR_FULL_CORE_SOAK=1`。
本文件只做几分钟内的 checkpoint、tiny backward 和 conversion smoke，不承载真实长时间训练。
"""

from __future__ import annotations

import gc
import json
import os
import time
import warnings
from pathlib import Path

import psutil
import pytest
import torch

from backend.service.application.models.rfdetr_core.config import (
    PretrainWeightsCompatibilityWarning,
    SegmentationTrainConfig,
    TrainConfig,
)
from backend.service.application.models.rfdetr_core.export._onnx import (
    export_onnx,
    resolve_rfdetr_onnx_output_names,
)
from backend.service.application.models.rfdetr_core.export.validation import (
    build_rfdetr_dummy_input,
    validate_rfdetr_onnx,
)
from backend.service.application.models.rfdetr_core.factory import (
    build_rfdetr_full_core_model,
    build_rfdetr_full_core_config,
)
from backend.service.application.models.rfdetr_core.models.weights import (
    analyze_rfdetr_checkpoint_coverage,
    analyze_rfdetr_checkpoint_load_coverage,
    load_rfdetr_checkpoint_state_dict,
)
from backend.service.application.models.rfdetr_core.training.module_model import (
    RFDETRModelModule,
)
from backend.service.application.models.rfdetr_core.utilities.tensors import NestedTensor
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)

_RUN_SOAK_ENV = "AMVISION_RUN_RFDETR_FULL_CORE_SOAK"
_RUN_CONVERSION_SOAK_ENV = "AMVISION_RUN_RFDETR_FULL_CORE_CONVERSION_SOAK"
_RUN_CHECKPOINT_SMOKE_ENV = "AMVISION_RUN_RFDETR_CHECKPOINT_SMOKE"
_MAX_TINY_BACKWARD_ITERATIONS = 50


def test_rfdetr_local_pretrained_checkpoint_coverage_smoke() -> None:
    """显式读取本地 RF-DETR 预训练权重并验证 full core 覆盖率。"""

    if os.environ.get(_RUN_CHECKPOINT_SMOKE_ENV) != "1":
        pytest.skip(
            f"设置 {_RUN_CHECKPOINT_SMOKE_ENV}=1 后才执行 RF-DETR 真实 checkpoint smoke。"
        )

    cases = _read_checkpoint_smoke_cases()
    summaries = []
    for task_type, scale, checkpoint_path in cases:
        state_dict = load_rfdetr_checkpoint_state_dict(checkpoint_path)
        num_classes = _infer_num_classes_from_rfdetr_state_dict(state_dict)
        model = build_rfdetr_full_core_model(
            task_type=task_type,
            model_scale=scale,
            num_classes=num_classes,
            pretrained_path=str(checkpoint_path),
            load_pretrained=False,
        )
        raw_coverage = analyze_rfdetr_checkpoint_coverage(
            model=model,
            checkpoint_path=checkpoint_path,
        )
        coverage = analyze_rfdetr_checkpoint_load_coverage(
            model=model,
            checkpoint_path=checkpoint_path,
        )
        if coverage.loadable_ratio < 1.0:
            raise AssertionError(
                f"RF-DETR {task_type}/{scale} checkpoint load-path 覆盖率不足："
                f"{coverage.loadable_key_count}/{coverage.model_key_count}"
            )
        summaries.append(
            {
                "task_type": task_type,
                "scale": scale,
                "checkpoint": str(checkpoint_path),
                "num_classes": num_classes,
                "coverage_kind": "load-path",
                "model_keys": coverage.model_key_count,
                "source_keys": coverage.source_key_count,
                "loadable_keys": coverage.loadable_key_count,
                "loadable_ratio": coverage.loadable_ratio,
                "raw_loadable_ratio": raw_coverage.loadable_ratio,
                "raw_shape_mismatch_keys": raw_coverage.shape_mismatch_keys,
            }
        )
        del model
        del state_dict
        gc.collect()

    print(json.dumps({"benchmark_name": "rfdetr-local-checkpoint-coverage", "items": summaries}, ensure_ascii=False))


def test_rfdetr_full_core_tiny_training_backward_soak(tmp_path: Path) -> None:
    """短时重复执行 RF-DETR tiny loss backward 并输出资源基线。"""

    _require_rfdetr_soak_enabled()
    iterations = _read_positive_int_env("AMVISION_RFDETR_FULL_CORE_SOAK_ITERATIONS", default=20)
    summaries = [
        _run_tiny_backward_soak(
            tmp_path=tmp_path,
            task_type=DETECTION_TASK_TYPE,
            image_size=64,
            train_config_type=TrainConfig,
            iterations=iterations,
        ),
        _run_tiny_backward_soak(
            tmp_path=tmp_path,
            task_type=SEGMENTATION_TASK_TYPE,
            image_size=72,
            train_config_type=SegmentationTrainConfig,
            iterations=iterations,
        ),
    ]

    print(json.dumps({"benchmark_name": "rfdetr-full-core-tiny-backward", "items": summaries}, ensure_ascii=False))


def test_rfdetr_full_core_onnx_conversion_validation_soak(tmp_path: Path) -> None:
    """显式执行 RF-DETR full core ONNX 导出和数值校验。"""

    _require_rfdetr_soak_enabled()
    if os.environ.get(_RUN_CONVERSION_SOAK_ENV) != "1":
        pytest.skip(
            f"设置 {_RUN_CONVERSION_SOAK_ENV}=1 后才执行 RF-DETR ONNX conversion soak。"
        )
    try:
        import onnx
        import onnxruntime
    except ImportError as exc:
        pytest.skip(f"RF-DETR ONNX conversion soak 缺少依赖：{exc}")

    tasks = _read_task_list_env(
        "AMVISION_RFDETR_FULL_CORE_CONVERSION_TASKS",
        default=(DETECTION_TASK_TYPE,),
    )
    summaries = []
    for task_type in tasks:
        image_size = 72 if task_type == SEGMENTATION_TASK_TYPE else 64
        module = _build_tiny_module(
            tmp_path=tmp_path,
            task_type=task_type,
            train_config_type=SegmentationTrainConfig if task_type == SEGMENTATION_TASK_TYPE else TrainConfig,
        )
        module.model.eval()
        output_names = resolve_rfdetr_onnx_output_names(task_type)
        dummy_input = build_rfdetr_dummy_input(
            input_height=image_size,
            input_width=image_size,
        )
        export_dir = tmp_path / "onnx" / task_type
        export_dir.mkdir(parents=True, exist_ok=True)
        started_at = time.perf_counter()
        exported_path = export_onnx(
            output_dir=str(export_dir),
            model=module.model,
            input_names=("image",),
            input_tensors=dummy_input,
            output_names=output_names,
            dynamic_axes=None,
            verbose=False,
            opset_version=17,
            variant_name=f"rfdetr-{task_type}-tiny-soak",
        )
        validation_summary = validate_rfdetr_onnx(
            model=module.model,
            dummy_input=dummy_input,
            onnx_path=Path(exported_path),
            onnx_module=onnx,
            onnxruntime_module=onnxruntime,
            output_names=output_names,
        )
        summaries.append(
            {
                "task_type": task_type,
                "onnx_path": exported_path,
                "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                "validation_summary": validation_summary,
            }
        )

    print(json.dumps({"benchmark_name": "rfdetr-full-core-onnx-conversion", "items": summaries}, ensure_ascii=False))


def _run_tiny_backward_soak(
    *,
    tmp_path: Path,
    task_type: str,
    image_size: int,
    train_config_type: type[TrainConfig],
    iterations: int,
) -> dict[str, object]:
    """重复执行 tiny backward 并记录内存和耗时。"""

    process = psutil.Process()
    module = _build_tiny_module(
        tmp_path=tmp_path,
        task_type=task_type,
        train_config_type=train_config_type,
    )
    module.train()
    start_memory = process.memory_info().rss
    start_cuda_memory = _cuda_memory_allocated()
    losses: list[float] = []
    started_at = time.perf_counter()
    for _ in range(iterations):
        module.model.zero_grad(set_to_none=True)
        samples, targets = _build_tiny_batch(
            image_size=image_size,
            include_masks=task_type == SEGMENTATION_TASK_TYPE,
        )
        outputs = module.model(samples, targets)
        loss_dict = module.criterion(outputs, targets)
        loss = sum(
            loss_dict[name] * module.criterion.weight_dict[name]
            for name in loss_dict
            if name in module.criterion.weight_dict
        )
        if not torch.isfinite(loss):
            raise AssertionError(f"RF-DETR {task_type} tiny backward loss 非有限值：{loss}")
        loss.backward()
        if _sum_gradient_abs(module.model) <= 0.0:
            raise AssertionError(f"RF-DETR {task_type} tiny backward 没有产生有效梯度")
        losses.append(float(loss.detach().cpu().item()))

    end_memory = process.memory_info().rss
    end_cuda_memory = _cuda_memory_allocated()
    return {
        "task_type": task_type,
        "iterations": iterations,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "start_memory_bytes": start_memory,
        "end_memory_bytes": end_memory,
        "memory_drift_bytes": end_memory - start_memory,
        "start_cuda_memory_bytes": start_cuda_memory,
        "end_cuda_memory_bytes": end_cuda_memory,
        "cuda_memory_drift_bytes": end_cuda_memory - start_cuda_memory,
        "first_loss": round(losses[0], 6),
        "last_loss": round(losses[-1], 6),
    }


def _build_tiny_module(
    *,
    tmp_path: Path,
    task_type: str,
    train_config_type: type[TrainConfig],
) -> RFDETRModelModule:
    """构造小尺寸 RF-DETR 训练 module。"""

    torch.manual_seed(0)
    model_config = build_rfdetr_full_core_config(
        task_type=task_type,
        model_scale="nano",
        num_classes=3,
        device="cpu",
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=PretrainWeightsCompatibilityWarning,
        )
        model_config.num_queries = 8
        model_config.num_select = 8
        model_config.group_detr = 1
    train_config = train_config_type(
        dataset_dir=str(tmp_path / task_type / "dataset"),
        output_dir=str(tmp_path / task_type / "output"),
        batch_size=1,
        grad_accum_steps=1,
        multi_scale=False,
        use_ema=False,
        tensorboard=False,
        num_workers=0,
        accelerator="cpu",
        devices=1,
        compute_val_loss=False,
        compute_test_loss=False,
    )
    return RFDETRModelModule(model_config, train_config)


def _build_tiny_batch(
    *,
    image_size: int,
    include_masks: bool,
) -> tuple[NestedTensor, list[dict[str, torch.Tensor]]]:
    """构造 RF-DETR tiny batch。"""

    image = torch.randn(1, 3, image_size, image_size)
    mask = torch.zeros((1, image_size, image_size), dtype=torch.bool)
    target: dict[str, torch.Tensor] = {
        "labels": torch.tensor([1], dtype=torch.long),
        "boxes": torch.tensor([[0.5, 0.5, 0.25, 0.25]], dtype=torch.float32),
        "orig_size": torch.tensor([image_size, image_size], dtype=torch.long),
        "size": torch.tensor([image_size, image_size], dtype=torch.long),
        "image_id": torch.tensor([0], dtype=torch.long),
    }
    if include_masks:
        target_mask = torch.zeros((1, image_size, image_size), dtype=torch.float32)
        start = image_size // 4
        end = image_size - start
        target_mask[:, start:end, start:end] = 1.0
        target["masks"] = target_mask
    return NestedTensor(image, mask), [target]


def _sum_gradient_abs(model: torch.nn.Module) -> float:
    """统计模型参数梯度绝对值总和。"""

    total = 0.0
    for parameter in model.parameters():
        if parameter.grad is None:
            continue
        total += float(parameter.grad.detach().abs().sum().item())
    return total


def _cuda_memory_allocated() -> int:
    """读取当前 CUDA 显存占用；无 CUDA 时返回 0。"""

    if not torch.cuda.is_available():
        return 0
    return int(torch.cuda.memory_allocated())


def _require_rfdetr_soak_enabled() -> None:
    """确认 RF-DETR full core soak 已显式启用。"""

    if os.environ.get(_RUN_SOAK_ENV) != "1":
        pytest.skip(f"设置 {_RUN_SOAK_ENV}=1 后才执行 RF-DETR full core soak。")


def _read_positive_int_env(name: str, *, default: int) -> int:
    """读取正整数环境变量。"""

    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    value = int(raw_value)
    if value < 1:
        raise ValueError(f"{name} 必须是正整数")
    if value > _MAX_TINY_BACKWARD_ITERATIONS:
        raise ValueError(
            f"{name} 最大只能设置为 {_MAX_TINY_BACKWARD_ITERATIONS}。"
            "测试里的训练验证只做短时 smoke，真实长时间训练应通过平台任务手动调试。"
        )
    return value


def _read_task_list_env(name: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    """读取任务类型列表环境变量。"""

    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    values = tuple(item.strip().lower() for item in raw_value.split(",") if item.strip())
    invalid = sorted(set(values) - {DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE})
    if invalid:
        raise ValueError(f"{name} 只支持 detection, segmentation，当前无效值：{invalid}")
    return values


def _read_checkpoint_smoke_cases() -> tuple[tuple[str, str, Path], ...]:
    """读取需要做真实 checkpoint smoke 的 RF-DETR 本地权重列表。"""

    raw_cases = os.environ.get("AMVISION_RFDETR_CHECKPOINT_SMOKE_CASES")
    values = (
        tuple(item.strip() for item in raw_cases.split(","))
        if raw_cases
        else _default_checkpoint_smoke_case_specs()
    )
    cases: list[tuple[str, str, Path]] = []
    for raw_value in values:
        if not raw_value:
            continue
        parts = raw_value.split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError(
                "AMVISION_RFDETR_CHECKPOINT_SMOKE_CASES 每项必须是 task_type:scale:path"
            )
        task_type, scale, checkpoint_path = parts
        if task_type not in {DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE}:
            raise ValueError(f"RF-DETR checkpoint smoke 不支持 task_type={task_type!r}")
        resolved_path = Path(checkpoint_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"RF-DETR checkpoint smoke 找不到本地权重：{resolved_path}")
        cases.append((task_type, scale, resolved_path))
    return tuple(cases)


def _default_checkpoint_smoke_case_specs() -> tuple[str, ...]:
    """返回当前平台预期提供的 RF-DETR 全 scale 本地 checkpoint 清单。"""

    return (
        "detection:nano:data/files/models/pretrained/rfdetr/detection/nano/default/checkpoints/rf-detr-nano.pth",
        "detection:s:data/files/models/pretrained/rfdetr/detection/s/default/checkpoints/rf-detr-small.pth",
        "detection:m:data/files/models/pretrained/rfdetr/detection/m/default/checkpoints/rf-detr-medium.pth",
        "detection:l:data/files/models/pretrained/rfdetr/detection/l/default/checkpoints/rf-detr-large.pth",
        "segmentation:nano:data/files/models/pretrained/rfdetr/segmentation/nano/default/checkpoints/rf-detr-seg-n-ft.pth",
        "segmentation:s:data/files/models/pretrained/rfdetr/segmentation/s/default/checkpoints/rf-detr-seg-s-ft.pth",
        "segmentation:m:data/files/models/pretrained/rfdetr/segmentation/m/default/checkpoints/rf-detr-seg-m-ft.pth",
        "segmentation:l:data/files/models/pretrained/rfdetr/segmentation/l/default/checkpoints/rf-detr-seg-l-ft.pth",
        "segmentation:x:data/files/models/pretrained/rfdetr/segmentation/x/default/checkpoints/rf-detr-seg-xl-ft.pth",
    )


def _infer_num_classes_from_rfdetr_state_dict(state_dict: dict[str, torch.Tensor]) -> int:
    """从 RF-DETR checkpoint 的 class head 推断平台 num_classes。"""

    class_bias_key = next((key for key in state_dict if key.endswith("class_embed.bias")), None)
    if class_bias_key is None:
        raise AssertionError("RF-DETR checkpoint 缺少 class_embed.bias，无法推断 num_classes")
    output_classes = int(state_dict[class_bias_key].shape[0])
    # full core 内部会额外加 no-object 类，平台侧 num_classes 是前景类数量。
    return max(output_classes - 1, 1)
