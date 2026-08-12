"""18 个公开模型/任务组合的真实小数据集端到端验收入口。

默认执行完整矩阵：DatasetImport -> DatasetExport -> 1 epoch 训练 -> 独立评估 ->
ONNX/OpenVINO/TensorRT 转换 -> 每种产物独立加载 -> sync/async 各一次推理 ->
deployment stop/reset。结果写入 ``.tmp/model-task-e2e-matrix/<run-id>/result.json``。

该入口使用真实本地数据、预训练权重、转换器和 runtime，不属于默认 pytest。
任一矩阵项失败都会保留其余项的结果，并最终返回非零退出码。
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.service.domain.models.yolo_model_profiles import YOLO_MODEL_SCALES
from tests.integration.yolo_model_full_chain_smoke import (
    DEFAULT_PROJECT_ID,
    DEFAULT_TOKEN,
    REQUIRED_CONVERSION_FORMATS,
    YOLO_MAIN_MODEL_TYPES,
    ManagedProcess,
    SmokeApiClient,
    YoloModelTaskCase,
    build_default_task_cases,
    collect_process_snapshots,
    find_free_port,
    run_task_case,
    start_service_processes,
    stop_managed_processes,
    wait_for_service,
    write_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX_ROOT = PROJECT_ROOT / ".tmp" / "model-task-e2e-matrix"
MAX_TRAINING_TEST_EVALUATION_METRIC_DELTA = 0.05
ALL_MODEL_TYPES = ("yolox", *YOLO_MAIN_MODEL_TYPES, "rfdetr")
ALL_TASK_TYPES = ("detection", "classification", "segmentation", "pose", "obb")
SUPPORTED_MODEL_TASK_PAIRS = (
    ("yolox", "detection"),
    *((model_type, "detection") for model_type in YOLO_MAIN_MODEL_TYPES),
    ("rfdetr", "detection"),
    *((model_type, "classification") for model_type in YOLO_MAIN_MODEL_TYPES),
    *((model_type, "segmentation") for model_type in YOLO_MAIN_MODEL_TYPES),
    ("rfdetr", "segmentation"),
    *((model_type, "pose") for model_type in YOLO_MAIN_MODEL_TYPES),
    *((model_type, "obb") for model_type in YOLO_MAIN_MODEL_TYPES),
)


@dataclass(frozen=True)
class ModelTaskMatrixCase:
    """描述一个可独立执行和审计的模型/任务链路。"""

    case_id: str
    model_type: str
    model_scale: str
    task_case: YoloModelTaskCase


def build_model_task_matrix() -> tuple[ModelTaskMatrixCase, ...]:
    """构造 18 个公开支持组合的唯一矩阵。"""

    task_cases = build_default_task_cases()
    matrix: list[ModelTaskMatrixCase] = []
    for model_type, task_type in SUPPORTED_MODEL_TASK_PAIRS:
        task_case = task_cases[task_type]
        if model_type in {"yolox", "rfdetr"} and task_type == "detection":
            task_case = replace(
                task_case,
                export_format="coco-detection-v1",
                input_size=(384, 384),
            )
        elif model_type == "rfdetr" and task_type == "segmentation":
            task_case = replace(
                task_case,
                export_format="coco-instance-seg-v1",
                input_size=(384, 384),
            )
        matrix.append(
            ModelTaskMatrixCase(
                case_id=f"{model_type}-{task_type}",
                model_type=model_type,
                model_scale="nano",
                task_case=task_case,
            )
        )
    return tuple(matrix)


def main(argv: list[str] | None = None) -> int:
    """执行选择后的矩阵，并为完整性和失败状态设置退出码。"""

    args = parse_args(argv)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d%H%M%S")
    run_dir = MATRIX_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    selected_cases = select_matrix_cases(
        model_types=set(args.models),
        task_types=set(args.tasks),
    )
    dataset_dir_override = resolve_dataset_dir_override(
        dataset_dir=args.dataset_dir,
        selected_cases=selected_cases,
    )
    is_full_scope = (
        len(selected_cases) == len(SUPPORTED_MODEL_TASK_PAIRS)
        and tuple(args.target_formats) == REQUIRED_CONVERSION_FORMATS
        and not args.skip_deployment
    )
    result: dict[str, Any] = {
        "contract_version": 1,
        "run_id": run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "coverage": "full" if is_full_scope else "partial",
        "required_case_count": len(SUPPORTED_MODEL_TASK_PAIRS),
        "selected_case_count": len(selected_cases),
        "required_conversion_formats": list(REQUIRED_CONVERSION_FORMATS),
        "selected_conversion_formats": list(args.target_formats),
        "benchmark_options": {
            "model_scale": args.model_scale or None,
            "input_size": list(args.input_size) if args.input_size else None,
            "enable_augmentation": args.enable_augmentation,
            "evaluation_interval": args.evaluation_interval,
            "max_epochs": args.max_epochs,
            "batch_mode": args.batch_mode,
            "batch_size": args.batch_size,
            "batch_target_memory_fraction": args.batch_target_memory_fraction,
            "batch_minimum_size": args.batch_minimum_size,
            "batch_maximum_size": args.batch_maximum_size,
            "batch_recover_on_oom": args.batch_recover_on_oom,
            "batch_max_oom_retries": args.batch_max_oom_retries,
            "checkpoint_interval": args.checkpoint_interval,
            "checkpoint_keep_periodic": args.checkpoint_keep_periodic,
            "max_images_per_split": args.max_images_per_split,
            "use_pretrained_warm_start": args.use_pretrained_warm_start,
            "training_precision": args.training_precision,
            "training_num_workers": args.training_num_workers,
            "training_prefetch_factor": args.training_prefetch_factor,
            "dataset_dir": (
                str(dataset_dir_override) if dataset_dir_override is not None else None
            ),
        },
        "cases": {},
        "processes": {},
    }
    processes: list[ManagedProcess] = []
    client: SmokeApiClient | None = None
    base_url = args.base_url

    try:
        if args.start_processes:
            port = args.port or find_free_port(args.port_start, args.port_end)
            base_url = f"http://127.0.0.1:{port}"
            processes = start_service_processes(
                run_dir=run_dir,
                port=port,
                service_timeout_seconds=args.service_timeout_seconds,
            )
        wait_for_service(
            base_url=base_url,
            timeout_seconds=args.service_timeout_seconds,
        )
        client = SmokeApiClient(
            base_url=base_url,
            token=args.token,
            timeout_seconds=args.http_timeout_seconds,
        )
        for matrix_case in selected_cases:
            case_run_dir = run_dir / matrix_case.case_id
            case_run_dir.mkdir(parents=True, exist_ok=True)
            task_case = matrix_case.task_case
            if dataset_dir_override is not None:
                task_case = replace(
                    task_case,
                    dataset_dir=dataset_dir_override,
                    dataset_archive=None,
                )
            if args.input_size is not None:
                task_case = replace(
                    task_case,
                    input_size=(int(args.input_size[0]), int(args.input_size[1])),
                )
            try:
                case_result = run_task_case(
                    client=client,
                    case=task_case,
                    run_dir=case_run_dir,
                    project_id=args.project_id,
                    model_type=matrix_case.model_type,
                    model_scale=args.model_scale or matrix_case.model_scale,
                    target_formats=tuple(args.target_formats),
                    max_epochs=args.max_epochs,
                    batch_size=args.batch_size,
                    training_device=args.training_device,
                    timeout_seconds=args.task_timeout_seconds,
                    skip_deployment=args.skip_deployment,
                    run_workflow=args.run_workflow,
                    max_images_per_split=args.max_images_per_split,
                    enable_augmentation=args.enable_augmentation,
                    evaluation_interval=args.evaluation_interval,
                    warm_start_model_version_id=(
                        resolve_pretrained_warm_start_model_version_id(
                            model_type=matrix_case.model_type,
                            task_type=matrix_case.task_case.task_type,
                            model_scale=args.model_scale or matrix_case.model_scale,
                        )
                        if args.use_pretrained_warm_start
                        else None
                    ),
                    training_precision=args.training_precision,
                    training_num_workers=args.training_num_workers,
                    training_prefetch_factor=args.training_prefetch_factor,
                    batch_mode=args.batch_mode,
                    batch_target_memory_fraction=(args.batch_target_memory_fraction),
                    batch_minimum_size=args.batch_minimum_size,
                    batch_maximum_size=args.batch_maximum_size,
                    batch_recover_on_oom=args.batch_recover_on_oom,
                    batch_max_oom_retries=args.batch_max_oom_retries,
                    checkpoint_interval=args.checkpoint_interval,
                    checkpoint_keep_periodic=args.checkpoint_keep_periodic,
                )
                validate_case_result(
                    case_result,
                    task_type=matrix_case.task_case.task_type,
                    target_formats=tuple(args.target_formats),
                    require_deployment=not args.skip_deployment,
                    require_workflow=args.run_workflow,
                )
                result["cases"][matrix_case.case_id] = case_result
            except Exception as error:  # noqa: BLE001 - 需要形成完整失败矩阵。
                result["cases"][matrix_case.case_id] = {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(error),
                }
                if args.fail_fast:
                    break
    except Exception as error:  # noqa: BLE001 - 顶层必须持久化启动失败。
        result["startup_error"] = str(error)
    finally:
        if client is not None:
            client.close()
        result["processes"] = collect_process_snapshots(processes)
        stop_managed_processes(processes)

    failed_case_ids = [
        case_id
        for case_id, case_result in result["cases"].items()
        if case_result.get("status") != "succeeded"
    ]
    missing_case_ids = [
        item.case_id for item in selected_cases if item.case_id not in result["cases"]
    ]
    result["failed_case_ids"] = failed_case_ids
    result["missing_case_ids"] = missing_case_ids
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    result["status"] = (
        "succeeded" if not failed_case_ids and not missing_case_ids else "failed"
    )
    write_result(run_dir=run_dir, result=result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "succeeded" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析矩阵选择、资源和执行参数。"""

    parser = argparse.ArgumentParser(description="运行模型/任务真实小数据集端到端矩阵")
    parser.add_argument("--base-url", default="http://127.0.0.1:5600")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=None,
        help=(
            "覆盖所选单一 task 的默认数据集目录；相对路径按仓库根目录解析，"
            "可同时供该 task 的多个 model family 使用"
        ),
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=ALL_MODEL_TYPES,
        default=ALL_MODEL_TYPES,
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=ALL_TASK_TYPES,
        default=ALL_TASK_TYPES,
    )
    parser.add_argument(
        "--target-formats",
        nargs="+",
        choices=("onnx", "openvino-ir", "tensorrt-engine"),
        default=REQUIRED_CONVERSION_FORMATS,
    )
    parser.add_argument("--max-epochs", type=int, default=1)
    parser.add_argument(
        "--batch-mode",
        choices=("auto", "fixed"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--batch-target-memory-fraction", type=float, default=0.6)
    parser.add_argument("--batch-minimum-size", type=int, default=1)
    parser.add_argument("--batch-maximum-size", type=int, default=None)
    parser.add_argument(
        "--batch-recover-on-oom",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--batch-max-oom-retries", type=int, default=3)
    parser.add_argument("--checkpoint-interval", type=int, default=5)
    parser.add_argument("--checkpoint-keep-periodic", type=int, default=2)
    parser.add_argument(
        "--model-scale",
        choices=YOLO_MODEL_SCALES,
        default=None,
        help="覆盖矩阵默认 model scale；省略时保持各 case 默认值",
    )
    parser.add_argument(
        "--input-size",
        nargs=2,
        type=int,
        metavar=("HEIGHT", "WIDTH"),
        default=None,
    )
    parser.add_argument("--enable-augmentation", action="store_true")
    parser.add_argument(
        "--use-pretrained-warm-start",
        action="store_true",
        help="使用本地 catalog 中与 family/task/scale 完全匹配的预训练版本",
    )
    parser.add_argument("--evaluation-interval", type=int, default=1)
    parser.add_argument("--training-device", default="auto")
    parser.add_argument(
        "--training-precision",
        choices=("auto", "fp32", "fp16", "bf16"),
        default="auto",
    )
    parser.add_argument("--training-num-workers", type=int, default=0)
    parser.add_argument("--training-prefetch-factor", type=int, default=2)
    parser.add_argument("--max-images-per-split", type=int, default=4)
    parser.add_argument("--task-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--http-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--service-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--start-processes", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--port-start", type=int, default=18360)
    parser.add_argument("--port-end", type=int, default=18460)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-workflow", action="store_true")
    parser.add_argument("--skip-deployment", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.max_epochs < 1
        or args.batch_size < 1
        or args.batch_minimum_size < 1
        or (
            args.batch_maximum_size is not None
            and args.batch_maximum_size < args.batch_minimum_size
        )
        or not 0.1 <= args.batch_target_memory_fraction <= 0.95
        or not 0 <= args.batch_max_oom_retries <= 10
        or args.checkpoint_interval < 1
        or args.checkpoint_keep_periodic < 1
        or args.evaluation_interval < 1
        or args.training_num_workers < 0
        or args.training_prefetch_factor < 1
    ):
        parser.error("训练、batch、checkpoint、evaluation 和 prefetch 参数不在有效范围")
    if args.input_size is not None and any(value < 32 for value in args.input_size):
        parser.error("input-size 的高和宽必须大于等于 32")
    if args.max_images_per_split < 0:
        parser.error("max-images-per-split 不能小于 0")
    if len(set(args.target_formats)) != len(args.target_formats):
        parser.error("target-formats 不能重复")
    return args


def resolve_dataset_dir_override(
    *,
    dataset_dir: Path | None,
    selected_cases: tuple[ModelTaskMatrixCase, ...],
) -> Path | None:
    """解析真实矩阵的数据集覆盖并拒绝跨 task 误用。"""

    if dataset_dir is None:
        return None
    selected_task_types = {
        matrix_case.task_case.task_type for matrix_case in selected_cases
    }
    if len(selected_task_types) != 1:
        raise ValueError("--dataset-dir 只能用于只选择一个 task 类型的矩阵")
    resolved = dataset_dir if dataset_dir.is_absolute() else PROJECT_ROOT / dataset_dir
    resolved = resolved.resolve()
    if not resolved.is_dir():
        raise ValueError(f"--dataset-dir 目录不存在：{resolved}")
    return resolved


def resolve_pretrained_warm_start_model_version_id(
    *,
    model_type: str,
    task_type: str,
    model_scale: str,
) -> str:
    """生成平台本地预训练 catalog 的稳定 ModelVersion id。

    当前精度矩阵只允许 YOLOv8/YOLO11/YOLO26 使用此快捷入口，避免把
    YOLOX、RF-DETR 的不同 catalog 命名和加载规则错误混入同一契约。
    """

    if model_type not in YOLO_MAIN_MODEL_TYPES:
        raise ValueError("--use-pretrained-warm-start 仅支持 yolov8、yolo11、yolo26")
    if task_type not in {"detection", "classification", "segmentation", "pose", "obb"}:
        raise ValueError(f"不支持预训练 warm-start 的任务类型: {task_type}")
    if model_scale not in YOLO_MODEL_SCALES:
        raise ValueError(f"不支持预训练 warm-start 的 model scale: {model_scale}")
    return f"mv-pretrained-{model_type}-{task_type}-{model_scale}"


def select_matrix_cases(
    *,
    model_types: set[str],
    task_types: set[str],
) -> tuple[ModelTaskMatrixCase, ...]:
    """按模型和任务交集选择合法组合。"""

    selected = tuple(
        case
        for case in build_model_task_matrix()
        if case.model_type in model_types and case.task_case.task_type in task_types
    )
    if not selected:
        raise ValueError("模型和任务筛选后没有合法矩阵项")
    return selected


def validate_case_result(
    result: dict[str, Any],
    *,
    task_type: str,
    target_formats: tuple[str, ...],
    require_deployment: bool,
    require_workflow: bool,
) -> None:
    """拒绝只有任务成功、但转换或加载推理不完整的假阳性结果。"""

    if result.get("status") != "succeeded":
        raise RuntimeError("端到端用例未成功")
    for required_key in (
        "dataset_version_id",
        "dataset_export_id",
        "training_task_id",
        "model_version_id",
    ):
        if not result.get(required_key):
            raise RuntimeError(f"端到端结果缺少 {required_key}")
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("state") != "succeeded":
        raise RuntimeError("端到端结果缺少成功的 evaluation")
    sample_count = evaluation.get("sample_count")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise RuntimeError("evaluation 没有处理有效样本")
    metric_pairs_by_task = {
        "detection": (("map50", "map50"), ("map50_95", "map50_95")),
        "classification": (
            ("top1_accuracy", "top1_accuracy"),
            ("top5_accuracy", "top5_accuracy"),
        ),
        "segmentation": (
            ("bbox_map50", "bbox_map50"),
            ("bbox_map50_95", "bbox_map50_95"),
            ("mask_map50", "mask_map50"),
            ("mask_map50_95", "mask_map50_95"),
        ),
        "pose": (("oks_ap50", "oks_ap50"), ("oks_ap50_95", "oks_ap50_95")),
        "obb": (("map50", "map50"), ("map50_95", "map50_95")),
    }
    metric_pairs = metric_pairs_by_task.get(task_type)
    if metric_pairs is None:
        raise RuntimeError(f"未知 evaluation task_type：{task_type}")
    missing_metrics = [
        evaluation_metric_name
        for evaluation_metric_name, _ in metric_pairs
        if not isinstance(evaluation.get(evaluation_metric_name), int | float)
    ]
    if missing_metrics:
        raise RuntimeError(
            f"{task_type} evaluation 缺少指标：{', '.join(missing_metrics)}"
        )
    training_test_metrics = result.get("training_test_metrics")
    if not isinstance(training_test_metrics, dict):
        raise RuntimeError("端到端结果缺少训练收尾 test 指标")
    for evaluation_metric_name, training_metric_name in metric_pairs:
        evaluation_value = float(evaluation[evaluation_metric_name])
        training_test_value = training_test_metrics.get(training_metric_name)
        if not isinstance(training_test_value, int | float):
            raise RuntimeError(f"训练收尾 test 缺少指标：{training_metric_name}")
        training_test_value = float(training_test_value)
        if (
            not math.isfinite(evaluation_value)
            or not math.isfinite(training_test_value)
            or not 0.0 <= evaluation_value <= 1.0
            or not 0.0 <= training_test_value <= 1.0
        ):
            raise RuntimeError(f"{evaluation_metric_name} 包含非有限值或超出 0..1")
        metric_delta = abs(evaluation_value - training_test_value)
        if metric_delta > MAX_TRAINING_TEST_EVALUATION_METRIC_DELTA:
            raise RuntimeError(
                "训练收尾 test 与独立 evaluation 指标不一致："
                f"metric={evaluation_metric_name}, test={training_test_value:.6f}, "
                f"evaluation={evaluation_value:.6f}, delta={metric_delta:.6f}"
            )
    conversions = result.get("conversions")
    if not isinstance(conversions, dict):
        raise RuntimeError("端到端结果缺少 conversions")
    if set(conversions) != set(target_formats):
        raise RuntimeError(
            f"转换结果不完整：expected={sorted(target_formats)}, "
            f"actual={sorted(conversions)}"
        )
    for target_format in target_formats:
        conversion = conversions[target_format]
        if not isinstance(conversion, dict) or not conversion.get("model_build_id"):
            raise RuntimeError(f"{target_format} 转换没有登记 ModelBuild")
        if not require_deployment:
            continue
        deployment = conversion.get("deployment")
        if not isinstance(deployment, dict):
            raise RuntimeError(f"{target_format} 没有执行 deployment 加载")
        if require_workflow:
            workflow = deployment.get("workflow")
            if not isinstance(workflow, dict):
                raise RuntimeError(f"{target_format} 没有执行 workflow")
            workflow_run = workflow.get("run")
            if (
                not isinstance(workflow_run, dict)
                or workflow_run.get("state") != "succeeded"
            ):
                raise RuntimeError(f"{target_format} workflow 未成功")
            if not workflow_run.get("output_keys"):
                raise RuntimeError(f"{target_format} workflow 没有输出")
        sync_result = deployment.get("sync")
        async_result = deployment.get("async")
        if not isinstance(sync_result, dict) or not isinstance(async_result, dict):
            raise RuntimeError(f"{target_format} 没有完成 sync/async 推理")
        if not sync_result.get("result_summary"):
            raise RuntimeError(f"{target_format} 没有完成 sync 推理")
        async_task = async_result.get("task")
        if not isinstance(async_task, dict) or async_task.get("state") != "succeeded":
            raise RuntimeError(f"{target_format} 没有完成 async 推理")
        for runtime_mode, runtime_result in (
            ("sync", sync_result),
            ("async", async_result),
        ):
            runtime_status = runtime_result.get("status")
            if (
                not isinstance(runtime_status, dict)
                or runtime_status.get("process_state") != "running"
            ):
                raise RuntimeError(
                    f"{target_format} {runtime_mode} deployment 未成功加载"
                )


if __name__ == "__main__":
    raise SystemExit(main())
